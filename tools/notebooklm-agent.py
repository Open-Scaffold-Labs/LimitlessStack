#!/usr/bin/env python3
"""Run a foreground job in an independently authenticated NotebookLM agent profile.

Bootstrap ~/.notebooklm-agents/profiles/bootstrap/master_token.json separately with
NotebookLM's supported login flow. This runner copies only that durable master token,
never browser cookies. Scripts spawned here inherit the profile for their CLI calls.
This is an ownership/concurrency guard for cooperating agents, not a shell sandbox.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time


class SetupError(Exception):
    pass


def profile_name(agent):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", agent):
        raise SetupError("agent must be a stable 1–160 character task id (letters, digits, . _ : -)")
    slug = re.sub(r"[^a-z0-9-]+", "-", agent.lower())[:36].strip("-")
    return "agent-" + slug + "-" + hashlib.sha256(agent.encode()).hexdigest()[:16]


def no_symlinks(path):
    for node in reversed((path, *path.parents)):
        if node.is_symlink():
            raise SetupError("managed paths must not contain symlinks")


def private_dir(path):
    no_symlinks(path)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise SetupError("managed directories must be owned by this user with mode 0700")


def private_file(path):
    no_symlinks(path)
    st = path.stat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
        raise SetupError("credential/ownership files must be private regular files with mode 0600")
    return path.read_bytes()


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def reject_overrides(command, cli):
    if Path(command[0]).name not in {"notebooklm", Path(cli).name}:
        return  # Trusted batch scripts inherit the managed environment.
    args = command[1:]
    forbidden = ("--profile", "--storage", "--profile-name", "--account", "--all-accounts",
                 "--browser-cookies", "--browser-cookie", "--oauth-token", "--force", "--fresh")
    for arg in args:
        if arg == "-p" or arg.startswith("-p") or any(arg == x or arg.startswith(x + "=") for x in forbidden):
            raise SetupError("profile/storage/account overrides are not allowed in a managed CLI job")
    if "auth" in args and "refresh" in args:
        raise SetupError("use runner --refresh before --; direct auth refresh bypasses the shared mint lock")
    if "login" in args or "logout" in args or "import-cookies" in args:
        raise SetupError("bootstrap or credential replacement must be performed outside managed jobs")
    if "profile" in args and any(x in args for x in ("create", "switch", "delete", "rename")):
        raise SetupError("profile mutations are not allowed in a managed CLI job")
    command[0] = cli


def auth_call(cli, args, env):
    try:
        result = subprocess.run([cli, *args], env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        raise SetupError("NotebookLM authentication could not complete; internal output suppressed") from None
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        data = {}
    return result.returncode, data if isinstance(data, dict) else {}


def healthy(cli, env):
    code, data = auth_call(cli, ["auth", "check", "--test", "--passive", "--json"], env)
    return code == 0 and data.get("status") == "ok" and data.get("checks", {}).get("token_fetch") is True


@contextmanager
def held_lock(path, timeout, label):
    no_symlinks(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        private_file(path)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SetupError(label + " is busy; lock timeout reached; no child job ran")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield lock


def ensure_auth(cli, env, storage, locks, timeout, refresh=False):
    if not refresh and storage.exists() and healthy(cli, env):
        return
    # Google session minting is serialized across profiles. Ordinary healthy
    # profile reads and child jobs never acquire this shared lock.
    with held_lock(locks / "session-mint.lock", timeout, "session minting"):
        if not refresh and storage.exists() and healthy(cli, env):
            return
        code, _ = auth_call(cli, ["auth", "refresh", "--verify", "--json"], env)
        if code != 0 or not healthy(cli, env):
            raise SetupError("managed authentication failed; profile retained; no child job ran (details suppressed)")
        private_file(storage)


def active_context():
    """Validate a runner child without trusting a marker or merely open lock FD."""
    env = os.environ
    name = env.get("NOTEBOOKLM_PROFILE", "")
    if not name or env.get("NOTEBOOKLM_AGENT_ACTIVE") != name or env.get("NOTEBOOKLM_AUTH_JSON"):
        raise SetupError("no managed runner context")
    home = Path(env.get("NOTEBOOKLM_HOME", ""))
    if not home.is_absolute() or ".." in home.parts:
        raise SetupError("invalid managed home")
    profile = home / "profiles" / name
    for path in (home, home / "profiles", home / "profiles/bootstrap", home / "locks", profile):
        private_dir(path)
    seed = private_file(home / "profiles/bootstrap/master_token.json")
    owner = json.loads(private_file(profile / ".agent-owner.json"))
    if (not isinstance(owner, dict) or profile_name(owner.get("agent", "")) != name
            or owner != {"schema": 1, "agent": owner["agent"], "profile": name,
                         "seed_sha256": hashlib.sha256(seed).hexdigest()}
            or private_file(profile / "master_token.json") != seed):
        raise SetupError("invalid managed profile ownership")
    private_file(profile / "storage_state.json")
    path = home / "locks" / (name + ".lock")
    private_file(path)
    fd = int(env.get("NOTEBOOKLM_AGENT_LOCK_FD", "-1"))
    if fd < 3:
        raise SetupError("missing inherited profile lock")
    held, expected = os.fstat(fd), path.stat()
    if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
        raise SetupError("inherited lock does not belong to this profile")
    with path.open("rb") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise SetupError("profile lock is not held")
    # Only the inherited owning open-file description can succeed while the
    # independent probe conflicts. Never unlock it: the parent owns its lifetime.
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv) == ["--check-managed-env"]:
        try:
            active_context()
            return 0
        except (SetupError, OSError, ValueError, TypeError, KeyError):
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, help="unique stable task id, reused by this task only")
    parser.add_argument("--home", default=str(Path.home() / ".notebooklm-agents"))
    parser.add_argument("--cli", default="notebooklm")
    parser.add_argument("--lock-timeout", type=float, default=60)
    parser.add_argument("--refresh", action="store_true", help="refresh this profile under the shared session-mint lock")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        name = profile_name(args.agent)
        home = Path(args.home).expanduser()
        if not home.is_absolute() or ".." in home.parts or home in {Path("/"), Path.home()}:
            raise SetupError("managed home must be an absolute dedicated directory without '..'")
        if not 0 <= args.lock_timeout <= 3600:
            raise SetupError("lock timeout must be between 0 and 3600 seconds")
        if not command:
            raise SetupError("a foreground command after -- is required")
        if os.environ.get("NOTEBOOKLM_AUTH_JSON"):
            raise SetupError("unset NOTEBOOKLM_AUTH_JSON before using managed profiles")
        cli = shutil.which(args.cli)
        if not cli:
            raise SetupError("NotebookLM CLI executable was not found")
        cli = str(Path(cli).absolute())
        reject_overrides(command, cli)
        for path in (home, home / "profiles", home / "profiles/bootstrap"):
            private_dir(path)
        seed = private_file(home / "profiles/bootstrap/master_token.json")
        try:
            seed_data = json.loads(seed)
        except ValueError:
            raise SetupError("bootstrap master-token file is not valid JSON") from None
        if not isinstance(seed_data, dict) or not seed_data:
            raise SetupError("bootstrap master-token file must be a nonempty JSON object")
        os.umask(0o077)
        locks = home / "locks"
        if not locks.exists():
            try:
                locks.mkdir(mode=0o700)
            except FileExistsError:
                pass
        private_dir(locks)
        lock_path = locks / (name + ".lock")
        with held_lock(lock_path, args.lock_timeout, "agent profile") as lock:
            profile = home / "profiles" / name
            owner = {"schema": 1, "agent": args.agent, "profile": name,
                     "seed_sha256": hashlib.sha256(seed).hexdigest()}
            if not profile.exists():
                profile.mkdir(mode=0o700)
                write_new(profile / "master_token.json", seed)
                write_new(profile / ".agent-owner.json", (json.dumps(owner) + "\n").encode())
            private_dir(profile)
            try:
                saved_owner = json.loads(private_file(profile / ".agent-owner.json"))
            except ValueError:
                raise SetupError("managed profile ownership record is invalid") from None
            if saved_owner != owner or private_file(profile / "master_token.json") != seed:
                raise SetupError("managed profile belongs to another task or bootstrap; existing files retained")
            storage = profile / "storage_state.json"
            if storage.exists() or storage.is_symlink():
                private_file(storage)
            env = os.environ.copy()
            env["NOTEBOOKLM_HOME"] = str(home)
            env["NOTEBOOKLM_PROFILE"] = name
            # A legacy external refresh hook could import a shared cookie snapshot.
            env.pop("NOTEBOOKLM_REFRESH_CMD", None)
            env["NOTEBOOKLM_AGENT_ACTIVE"] = name
            env["NOTEBOOKLM_AGENT_LOCK_FD"] = str(lock.fileno())
            ensure_auth(cli, env, storage, locks, args.lock_timeout, args.refresh)
            result = subprocess.run(command, env=env, pass_fds=(lock.fileno(),))
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except (SetupError, OSError) as error:
        # Never include arbitrary OS filenames or subprocess output in auth diagnostics.
        message = str(error) if isinstance(error, SetupError) else "managed file/process operation failed; existing files retained"
        print("notebooklm-agent: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
