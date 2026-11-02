#!/usr/bin/env python3
"""Network-free behavior tests for managed NotebookLM sessions (no real credentials)."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).with_name("notebooklm-agent.py")
FAKE = r'''#!/usr/bin/env python3
import json,os,sys,time,uuid
from pathlib import Path
p=Path(os.environ['NOTEBOOKLM_HOME'])/'profiles'/os.environ['NOTEBOOKLM_PROFILE']
s=p/'storage_state.json'
a=sys.argv[1:]
if a[:2]==['auth','check']:
 ok=s.exists() and not os.environ.get('FAKE_EXPIRE')
 print(json.dumps({'status':'ok' if ok else 'error','checks':{'token_fetch':ok}}))
 sys.exit(0 if ok else 1)
if a[:2]==['auth','refresh']:
 def event(kind):
  if os.environ.get('FAKE_REFRESH_LOG'):
   with open(os.environ['FAKE_REFRESH_LOG'],'a') as f:
    f.write(json.dumps({'kind':kind,'profile':p.name,'time':time.monotonic()})+'\n')
 event('start');time.sleep(float(os.environ.get('FAKE_REFRESH_SLEEP','0')))
 if os.environ.get('FAKE_AUTH_FAIL'):
  print('DO-NOT-LEAK-SECRET');print('DO-NOT-LEAK-SECRET',file=sys.stderr);sys.exit(1)
 s.write_text(json.dumps({'session':str(uuid.uuid4())}));s.chmod(0o600)
 event('end');print(json.dumps({'status':'ok'}));sys.exit(0)
print(json.dumps({'home':os.environ['NOTEBOOKLM_HOME'],'profile':os.environ['NOTEBOOKLM_PROFILE']}))
'''
JOB = r'''
import json,os,time
from pathlib import Path
p=Path(os.environ['JOB_LOG'])
def mark(kind):
 with p.open('a') as f:f.write(json.dumps({'kind':kind,'time':time.monotonic(),'pid':os.getpid(),'profile':os.environ['NOTEBOOKLM_PROFILE']})+'\n')
mark('start');time.sleep(float(os.environ.get('JOB_SLEEP','.3')));mark('end')
'''


class ManagedAgent(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "managed"
        self.seed_dir = self.home / "profiles/bootstrap"
        self.seed_dir.mkdir(parents=True, mode=0o700)
        for p in (self.home, self.home / "profiles", self.seed_dir):
            p.chmod(0o700)
        self.seed = self.seed_dir / "master_token.json"
        self.seed.write_text('{"master_token":"fake-secret-for-test-only"}\n')
        self.seed.chmod(0o600)
        self.seed_cookie = self.seed_dir / "storage_state.json"
        self.seed_cookie.write_text('{"session":"bootstrap-session-must-never-be-copied"}')
        self.seed_cookie.chmod(0o600)
        self.cli = self.root / "notebooklm"
        self.cli.write_text(FAKE)
        self.cli.chmod(0o700)
        self.env = os.environ.copy()
        self.env.pop("NOTEBOOKLM_AUTH_JSON", None)
        self.env.pop("FAKE_EXPIRE", None)
        self.env.pop("FAKE_AUTH_FAIL", None)
        self.env["JOB_LOG"] = str(self.root / "events.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, agent="first", child=None, extra=None):
        return [sys.executable, str(RUNNER), "--home", str(self.home), "--cli", str(self.cli),
                "--agent", agent, *(extra or []), "--", *(child or [str(self.cli), "list", "--json"])]

    def run_agent(self, agent="first", child=None, extra=None, env=None):
        return subprocess.run(self.command(agent, child, extra), capture_output=True, text=True,
                              env=env or self.env, timeout=10)

    def worker_dirs(self):
        return sorted(p for p in (self.home / "profiles").iterdir() if p.name != "bootstrap")

    def events(self):
        p = Path(self.env["JOB_LOG"])
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def wait_for_start(self):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if any(x["kind"] == "start" for x in self.events()):
                return
            time.sleep(.02)
        self.fail("foreground child did not start")

    def test_new_profiles_mint_independent_sessions_never_copy_cookies(self):
        self.assertEqual(self.run_agent("one").returncode, 0)
        self.assertEqual(self.run_agent("two").returncode, 0)
        workers = self.worker_dirs()
        self.assertEqual(len(workers), 2)
        sessions = [json.loads((p / "storage_state.json").read_text())["session"] for p in workers]
        self.assertEqual(len(set(sessions)), 2)
        self.assertNotIn("bootstrap-session-must-never-be-copied", sessions)
        for p in workers:
            self.assertEqual((p / "master_token.json").read_bytes(), self.seed.read_bytes())
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)
            for f in p.iterdir():
                self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.home / "locks").stat().st_mode), 0o700)
        self.assertFalse((self.home / "config.json").exists())

    def test_same_agent_reuses_session_and_propagates_exit(self):
        self.assertEqual(self.run_agent().returncode, 0)
        worker = self.worker_dirs()[0]
        before = (worker / "storage_state.json").read_bytes()
        result = self.run_agent(child=[sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(result.returncode, 7)
        self.assertEqual((worker / "storage_state.json").read_bytes(), before)

    def test_same_agent_jobs_serialize_for_entire_child_lifetime(self):
        cmd = self.command(child=[sys.executable, "-c", JOB])
        a = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_for_start()
        b = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        a.communicate(timeout=10); b.communicate(timeout=10)
        self.assertEqual((a.returncode, b.returncode), (0, 0))
        self.assertEqual([x["kind"] for x in self.events()], ["start", "end", "start", "end"])

    def test_different_agent_jobs_can_overlap(self):
        self.assertEqual(self.run_agent("a").returncode, 0)
        self.assertEqual(self.run_agent("b").returncode, 0)
        env = self.env | {"JOB_SLEEP": ".8"}
        a = subprocess.Popen(self.command("a", [sys.executable, "-c", JOB]), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_for_start()
        b = subprocess.Popen(self.command("b", [sys.executable, "-c", JOB]), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        a.communicate(timeout=10); b.communicate(timeout=10)
        self.assertEqual((a.returncode, b.returncode), (0, 0))
        self.assertEqual([x["kind"] for x in self.events()][:2], ["start", "start"])
        self.assertEqual(len({x["profile"] for x in self.events()}), 2)

    def test_new_profile_session_minting_serializes_across_agents(self):
        log = self.root / "refresh.jsonl"
        env = self.env | {"FAKE_REFRESH_LOG": str(log), "FAKE_REFRESH_SLEEP": ".3"}
        processes = [subprocess.Popen(self.command(agent), env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for agent in ("mint-a", "mint-b")]
        results = [p.communicate(timeout=10) for p in processes]
        self.assertEqual([p.returncode for p in processes], [0, 0], results)
        events = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([x["kind"] for x in events], ["start", "end", "start", "end"])
        self.assertNotEqual(events[0]["profile"], events[2]["profile"])

    def test_explicit_refresh_rotates_only_selected_profile(self):
        self.assertEqual(self.run_agent("a").returncode, 0)
        self.assertEqual(self.run_agent("b").returncode, 0)
        before = {p.name: (p / "storage_state.json").read_bytes() for p in self.worker_dirs()}
        self.assertEqual(self.run_agent("a", extra=["--refresh"]).returncode, 0)
        after = {p.name: (p / "storage_state.json").read_bytes() for p in self.worker_dirs()}
        changed = [name for name in before if before[name] != after[name]]
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0].startswith("agent-a-"))

    def test_reentry_requires_owned_profile_and_inherited_held_lock(self):
        child = ["bash", "-c", '"$1" "$2" --check-managed-env', "check", sys.executable, str(RUNNER)]
        self.assertEqual(self.run_agent(child=child).returncode, 0)
        profile = self.worker_dirs()[0].name
        env = self.env | {"NOTEBOOKLM_HOME": str(self.home), "NOTEBOOKLM_PROFILE": profile,
                          "NOTEBOOKLM_AGENT_ACTIVE": profile, "NOTEBOOKLM_AGENT_LOCK_FD": "9876"}
        result = subprocess.run([sys.executable, str(RUNNER), "--check-managed-env"], env=env,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        # A correct inode with an open but unlocked FD is still not valid.
        with (self.home / "locks" / (profile + ".lock")).open("rb") as lock:
            env["NOTEBOOKLM_AGENT_LOCK_FD"] = str(lock.fileno())
            result = subprocess.run([sys.executable, str(RUNNER), "--check-managed-env"], env=env,
                                    pass_fds=(lock.fileno(),), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_lock_timeout_runs_no_second_child(self):
        env = self.env | {"JOB_SLEEP": ".6"}
        a = subprocess.Popen(self.command(child=[sys.executable, "-c", JOB]), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_for_start()
        result = self.run_agent(child=[sys.executable, "-c", JOB], extra=["--lock-timeout", ".05"])
        a.communicate(timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("lock timeout", result.stderr)
        self.assertEqual([x["kind"] for x in self.events()], ["start", "end"])

    def test_auth_failure_preserves_existing_files_and_suppresses_internal_output(self):
        self.assertEqual(self.run_agent().returncode, 0)
        worker = self.worker_dirs()[0]
        before = {f.name: f.read_bytes() for f in worker.iterdir()}
        result = self.run_agent(child=[sys.executable, "-c", JOB],
                                env=self.env | {"FAKE_EXPIRE": "1", "FAKE_AUTH_FAIL": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("DO-NOT-LEAK-SECRET", result.stdout + result.stderr)
        self.assertEqual(before, {f.name: f.read_bytes() for f in worker.iterdir()})
        self.assertFalse(self.events())

    def test_bad_arguments_make_no_profile_changes(self):
        for agent, extra in [("../escape", []), ("valid", ["--lock-timeout", "-1"]),
                             ("valid", ["--home", str(self.home / ".." / "elsewhere")])]:
            with self.subTest(agent=agent, extra=extra):
                result = self.run_agent(agent, extra=extra)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.worker_dirs(), [])
                self.assertFalse((self.home / "locks").exists())

    def test_direct_cli_ownership_overrides_are_rejected_before_mutation(self):
        for args in [["--profile", "other", "list"], ["-pother", "list"],
                     ["--storage=/tmp/other", "list"], ["login"], ["auth", "logout"],
                     ["auth", "import-cookies", "-"], ["profile", "switch", "default"],
                     ["auth", "refresh"], ["auth", "refresh", "--browser-cookies", "chrome"]]:
            with self.subTest(args=args):
                result = self.run_agent(child=[str(self.cli), *args])
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.worker_dirs(), [])
                self.assertFalse((self.home / "locks").exists())

    def test_inline_auth_and_symlink_paths_fail_closed(self):
        result = self.run_agent(env=self.env | {"NOTEBOOKLM_AUTH_JSON": "not-a-real-secret"})
        self.assertEqual(result.returncode, 2)
        alias = self.root / "alias"
        alias.symlink_to(self.home, target_is_directory=True)
        result = self.run_agent(extra=["--home", str(alias)])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.worker_dirs(), [])
        self.assertFalse((self.home / "locks").exists())

    def test_seed_symlink_or_world_readable_seed_is_not_used(self):
        self.seed.chmod(0o644)
        self.assertEqual(self.run_agent().returncode, 2)
        self.seed.chmod(0o600)
        moved = self.root / "original-seed"
        self.seed.rename(moved)
        self.seed.symlink_to(moved)
        self.assertEqual(self.run_agent().returncode, 2)
        self.assertFalse((self.home / "locks").exists())

    def test_changed_bootstrap_does_not_overwrite_owned_profile(self):
        self.assertEqual(self.run_agent().returncode, 0)
        worker = self.worker_dirs()[0]
        before = {f.name: f.read_bytes() for f in worker.iterdir()}
        self.seed.write_text('{"master_token":"different-fake-token"}')
        self.assertEqual(self.run_agent().returncode, 2)
        self.assertEqual(before, {f.name: f.read_bytes() for f in worker.iterdir()})

    def test_unmanaged_existing_profile_or_symlink_cookie_is_not_overwritten(self):
        self.assertEqual(self.run_agent().returncode, 0)
        worker = self.worker_dirs()[0]
        owner = worker / ".agent-owner.json"
        previous = owner.read_bytes()
        owner.unlink()
        self.assertEqual(self.run_agent().returncode, 2)
        self.assertFalse(owner.exists())
        owner.write_bytes(previous); owner.chmod(0o600)
        storage = worker / "storage_state.json"
        original = self.root / "external-cookie"
        storage.rename(original)
        storage.symlink_to(original)
        self.assertEqual(self.run_agent().returncode, 2)
        self.assertTrue(storage.is_symlink())

    def test_refresh_hook_removed_and_managed_environment_used(self):
        env = self.env | {"NOTEBOOKLM_HOME": "/old/shared", "NOTEBOOKLM_PROFILE": "default",
                          "NOTEBOOKLM_REFRESH_CMD": "must-not-run"}
        result = self.run_agent(child=[sys.executable, "-c", "import os,json;print(json.dumps({k:os.getenv(k) for k in ['NOTEBOOKLM_HOME','NOTEBOOKLM_PROFILE','NOTEBOOKLM_REFRESH_CMD']}))"], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["NOTEBOOKLM_HOME"], str(self.home))
        self.assertTrue(value["NOTEBOOKLM_PROFILE"].startswith("agent-first-"))
        self.assertIsNone(value["NOTEBOOKLM_REFRESH_CMD"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
