#!/usr/bin/env python3
"""Fence for tools/notebooklm_external.py — runs offline against a fake notebook.

Each case states what must happen AND is paired with the thing that must not:
a managed copy is never deleted, a stray is never deleted before the managed copy is
verified or before its text is saved, an unchanged file is never re-uploaded, and a
source nobody manages is reported rather than silently accepted.
Run: python3.11 tools/test-notebooklm-external.py   (exit 0 = all pass)
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ext", HERE / "notebooklm_external.py")
ext = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ext)

NB = "9c8f3df0-aaaa-bbbb-cccc-000000000000"
FAILS = []


def expect(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class Fake:
    def __init__(self, tmp, sources, role="owner", verify_ok=True, fulltext_ok=True):
        self.TOOLS = self.STATE_DIR = Path(tmp)
        self.MEMBER = {"role": role}
        self.sources = list(sources)            # [{"id","title"}]
        self.verify_ok = verify_ok
        self.fulltext_ok = fulltext_ok
        self.calls = []
        self.uploaded = []                      # the text of every upload, in order
        self.NOTEBOOK_ROUTES = [("wiki/apps/openfirehouse", NB, "openfirehouse", "openfirehouse")]
        self.rules = Path(tmp) / "CLAUDE.md"
        self.rules.write_text("rules v1\n")
        self._MANIFEST = {
            "NOTEBOOKLM_EXTERNAL": [{"path": str(self.rules), "label": "openfirehouse",
                                     "title": "openfirehouse-rules-CLAUDE.md", "hand_titles": ["CLAUDE.md"]}],
            "NOTEBOOKLM_FROZEN": {"9c8f3df0": ["SPEC-2026-07-22.md"]},
            "NOTEBOOKLM_ACCOUNTED": ["9c8f3df0"],
            "NOTEBOOKLM_REMOVED_BACKUP": str(Path(tmp) / "removed"),
        }
        (Path(tmp) / ".notebooklm-openfirehouse-state.json").write_text(
            json.dumps({"wiki/apps/openfirehouse.md": {"source_id": "wiki-owned-1"}}))
        self._n = 0

    def route_for_label(self, label):
        return NB, label, label

    def state_file_for(self, label):
        return self.STATE_DIR / f".notebooklm-{label}-state.json"

    def activate_notebook(self, nb):
        pass

    def run_nb(self, args):
        r = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ["source", "list"]:
            r.stdout = json.dumps({"sources": self.sources})
        elif args[:2] == ["source", "fulltext"]:
            r.stdout = json.dumps({"content": "saved text" if self.fulltext_ok else ""})
        return r

    def cmd_add(self, path):
        self._n += 1
        sid = f"new-{self._n}"
        self.sources.append({"id": sid, "title": Path(path).name})
        self.calls.append(("add", Path(path).name))
        self.uploaded.append(Path(path).read_text())
        return sid

    def cmd_verify_content(self, sid, path, wait_retries=5):
        self.calls.append(("verify", sid))
        return self.verify_ok

    def cmd_replace(self, path, old):
        sid = self.cmd_add(path)
        self.calls.append(("replace", old))
        if self.verify_ok:
            self.sources = [s for s in self.sources if s["id"] != old]
        return sid, self.verify_ok, self.verify_ok

    def heal_verify(self, path, sid, attempts=2):
        return sid, self.verify_ok, False

    def cmd_delete(self, sid):
        self.calls.append(("delete", sid))
        before = len(self.sources)
        self.sources = [s for s in self.sources if s["id"] != sid]
        return len(self.sources) < before


def run_check(f):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ext.check(f)
    return rc, buf.getvalue()


def quiet(fn, *a, **k):
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


print("check:")
with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "wiki-owned-1", "title": "openfirehouse.md"},
                 {"id": "frozen-1", "title": "SPEC-2026-07-22.md"}])
    rc, out = run_check(f)
    expect(rc == 1 and "never synced" in out, "an external file never synced is STALE")
    expect("UNACCOUNTED" not in out, "wiki-owned and frozen sources are not reported")
    expect("NO_GIT_REF" not in out, "a file outside any git repository is never reported as NO_GIT_REF")
    quiet(ext.sync_externals, f, "openfirehouse")
    rc, out = run_check(f)
    expect(rc == 0, "after a sync, a clean notebook checks clean (exit 0)")
    f.rules.write_text("rules v2\n")
    rc, out = run_check(f)
    expect(rc == 1 and "file changed" in out, "an edited file is STALE")
    quiet(ext.sync_externals, f, "openfirehouse")
    f.sources.append({"id": "hand-1", "title": "CLAUDE.md"})
    rc, out = run_check(f)
    expect(rc == 1 and "hand-uploaded copy" in out, "a hand-uploaded copy is STALE (the refresh removes it)")
    f.sources.append({"id": "mystery-1", "title": "log.md"})
    rc, out = run_check(f)
    expect("UNACCOUNTED\t9c8f3df0\tmystery-1\tlog.md" in out, "a source nobody manages is UNACCOUNTED")

print("sync:")
with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "hand-1", "title": "CLAUDE.md"}, {"id": "hand-2", "title": "CLAUDE.md"}])
    c = quiet(ext.sync_externals, f, "openfirehouse")
    ids = {s["id"] for s in f.sources}
    expect(c["added"] == 1 and "new-1" in ids, "the managed copy is added under its distinct title")
    expect("hand-1" not in ids and "hand-2" not in ids, "both hand copies are removed after the managed copy verifies")
    expect(len(list((Path(t) / "removed").rglob("*.txt"))) == 2, "each removed copy's text is saved first")
    f.calls.clear()
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(c["unchanged"] == 1 and not any(k in ("add", "replace", "delete") for k, _ in f.calls),
           "an unchanged file is not re-uploaded and nothing is deleted")

with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "hand-1", "title": "CLAUDE.md"}], verify_ok=False)
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect("hand-1" in {s["id"] for s in f.sources}, "a stray is KEPT when the managed copy did not verify")
    expect(c["failed"] == 1, "an unverified upload is counted as failed")

with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [])
    quiet(ext.sync_externals, f, "openfirehouse")          # v1 synced and verified
    f.rules.write_text("rules v2\n")
    f.verify_ok = False                                     # the v2 upload will not verify
    f.sources.append({"id": "hand-9", "title": "CLAUDE.md"})
    quiet(ext.sync_externals, f, "openfirehouse")
    expect("hand-9" in {s["id"] for s in f.sources},
           "a stray is KEPT when an EARLIER copy verified but this run's upload did not")

with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "hand-1", "title": "CLAUDE.md"}], fulltext_ok=False)
    quiet(ext.sync_externals, f, "openfirehouse")
    expect("hand-1" in {s["id"] for s in f.sources}, "a stray is KEPT when its text could not be saved")

with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "hand-1", "title": "CLAUDE.md"}], role="member")
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(not f.calls and c["added"] == 0, "a teammate's run touches nothing (owner only)")
    rc, out = run_check(f)
    expect(rc == 0 and out.startswith("SKIP"), "a teammate's check skips")

with tempfile.TemporaryDirectory() as t:
    f = Fake(t, [{"id": "old-managed", "title": "openfirehouse-rules-CLAUDE.md"}])
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(c["adopted"] == 1 and "old-managed" in {s["id"] for s in f.sources},
           "an existing copy with the managed title and matching content is adopted, not re-uploaded")

# ── git_ref: a repo file is sent as it is on GitHub, not as it sits in a folder (2026-10-03) ──
# Each case uses throwaway repos: a bare "GitHub", the folder the config points at (cloned
# once and never updated — the stale folder that caused this), and another lane that pushes.
import subprocess


def git(cwd, *a):
    r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def capture(fn, *a, **k):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(*a, **k)
    return res, buf.getvalue()


class Repo:
    def __init__(self, tmp, first="v1\n"):
        tmp = Path(tmp)
        self.origin = tmp / "github.git"
        git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.lane = self._clone(tmp / "lane", empty=True)
        self.push(first)
        self.folder = self._clone(tmp / "folder")

    def _clone(self, where, empty=False):
        git(where.parent, "clone", "-q", str(self.origin), str(where))
        for k, v in (("user.email", "test@example.com"), ("user.name", "Test"),
                     ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
            git(where, "config", k, v)
        if empty:
            git(where, "checkout", "-q", "-b", "main")
        return where

    def push(self, text, name="CHANGELOG.md"):
        (self.lane / name).write_text(text)
        git(self.lane, "add", name)
        git(self.lane, "commit", "-q", "-m", text.strip())
        git(self.lane, "push", "-q", "origin", "main")
        return git(self.lane, "rev-parse", "HEAD")


def git_entry(path, ref="origin/main"):
    e = {"path": str(path), "label": "openfirehouse", "title": "openfirehouse-CHANGELOG.md",
         "hand_titles": ["CHANGELOG.md"]}
    if ref:
        e["git_ref"] = ref
    return e


def with_entry(f, e):
    f._MANIFEST["NOTEBOOKLM_EXTERNAL"] = [e]
    return f


def receipt(f, title="openfirehouse-CHANGELOG.md"):
    return json.loads((f.STATE_DIR / ext.STATE_NAME).read_text()).get(title, {})


print("git_ref:")
with tempfile.TemporaryDirectory() as t:
    r = Repo(t)
    v2 = r.push("v2\n")                       # another lane ships; nobody updates the folder
    f = with_entry(Fake(t, []), git_entry(r.folder / "CHANGELOG.md"))
    c, out = capture(ext.sync_externals, f, "openfirehouse", dry_run=True)
    expect(not f.uploaded and f"from origin/main at {v2[:7]}" in out,
           "a dry run sends nothing and names the branch and commit it would send")
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(c["added"] == 1 and f.uploaded == ["v2\n"],
           "sync sends the file as it is on GitHub (v2), not the stale folder's copy (v1)")
    rec = receipt(f)
    expect(rec.get("git_ref") == "origin/main" and rec.get("git_commit") == v2,
           "the receipt records the branch and the commit that was sent")
    rc, out = run_check(f)
    expect((r.folder / "CHANGELOG.md").read_text() == "v1\n" and rc == 0,
           "check agrees with sync: clean while the folder still holds v1")
    v3 = r.push("v3\n")
    rc, out = run_check(f)
    expect(rc == 1 and "changed on origin/main" in out,
           "a new push makes check STALE although the folder never changed")
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(c["replaced"] == 1 and f.uploaded[-1] == "v3\n" and receipt(f).get("git_commit") == v3,
           "the next sync sends the new version")
    rc, out = run_check(f)
    expect(rc == 0, "and check is clean again")

    r.push("v4\n")                            # pushed, but this machine cannot reach GitHub
    git(r.folder, "remote", "set-url", "origin", str(Path(t) / "nowhere.git"))
    s2 = Path(t) / "s2"
    s2.mkdir()
    g = with_entry(Fake(s2, []), git_entry(r.folder / "CHANGELOG.md"))
    c, out = capture(ext.sync_externals, g, "openfirehouse")
    expect(g.uploaded == ["v3\n"] and "could not fetch origin/main" in out,
           "GitHub unreachable: the branch as last fetched (v3) is sent and the run says so — never the folder (v1)")

with tempfile.TemporaryDirectory() as t:
    r = Repo(t)
    f = with_entry(Fake(t, [{"id": "hand-1", "title": "CHANGELOG.md"}]),
                   git_entry(r.folder / "MISSING.md"))
    c, out = capture(ext.sync_externals, f, "openfirehouse")
    expect(c["failed"] == 1 and c["skipped"] == 0 and not f.uploaded and "is not on origin/main" in out,
           "a file the branch does not have is a failure, not a quiet skip, and nothing is sent")
    expect("hand-1" in {s["id"] for s in f.sources}, "and nothing is deleted")
    rc, out = run_check(f)
    expect(rc == 2 and out.startswith("ERROR"), "check says it could not read it (exit 2)")

with tempfile.TemporaryDirectory() as t:
    r = Repo(t)
    r.push("v2\n")
    f = with_entry(Fake(t, []), git_entry(r.folder / "CHANGELOG.md", ref=None))
    quiet(ext.sync_externals, f, "openfirehouse")
    expect(f.uploaded == ["v1\n"], "an entry WITHOUT git_ref still sends the folder's copy, as before")
    expect(set(receipt(f)) == {"path", "notebook", "source_id", "sha256", "verified_at"},
           "and its receipt has exactly the fields it had before")
    s3 = Path(t) / "s3"
    s3.mkdir()
    gone = with_entry(Fake(s3, []), git_entry(Path(t) / "gone" / "CHANGELOG.md"))
    c = quiet(ext.sync_externals, gone, "openfirehouse")
    expect(c["skipped"] == 1 and not gone.uploaded, "a repository that is not on this machine is skipped, as before")
    rc, _ = run_check(gone)
    expect(rc == 0, "and check ignores it, as before")

with tempfile.TemporaryDirectory() as t:
    r = Repo(t)                               # the folder is current: same text as GitHub
    f = with_entry(Fake(t, []), git_entry(r.folder / "CHANGELOG.md", ref=None))
    quiet(ext.sync_externals, f, "openfirehouse")
    with_entry(f, git_entry(r.folder / "CHANGELOG.md"))    # now switch git_ref on
    rc, out = run_check(f)
    expect(rc == 0, "switching git_ref on: a receipt made from the folder stays valid when the text matches")
    f.calls.clear()
    c = quiet(ext.sync_externals, f, "openfirehouse")
    expect(c["unchanged"] == 1 and not any(k == "add" for k, _ in f.calls),
           "and nothing is re-uploaded")

print("NO_GIT_REF — a file in git that has no git_ref:")
with tempfile.TemporaryDirectory() as t:
    r = Repo(t)
    f = with_entry(Fake(t, []), git_entry(r.folder / "CHANGELOG.md", ref=None))   # no git_ref key
    quiet(ext.sync_externals, f, "openfirehouse")
    rc, out = run_check(f)
    expect(rc == 1 and "NO_GIT_REF\topenfirehouse\topenfirehouse-CHANGELOG.md\t" in out,
           "a file committed in git with no git_ref is reported")
    e = git_entry(r.folder / "CHANGELOG.md", ref=None)
    e["git_ref"] = None                                                     # folder, on purpose
    rc, out = run_check(with_entry(f, e))
    expect(rc == 0 and "NO_GIT_REF" not in out, '"git_ref": None (the folder, on purpose) is not reported')
    rc, out = run_check(with_entry(f, git_entry(r.folder / "CHANGELOG.md")))
    expect(rc == 0 and "NO_GIT_REF" not in out, 'an entry with "git_ref": "origin/main" is not reported')
    (r.folder / ".gitignore").write_text("CLAUDE.md\n")
    for name in ("CLAUDE.md", "LOCAL.md"):                                  # ignored, untracked
        (r.folder / name).write_text("only here\n")
        e = git_entry(r.folder / name, ref=None)
        e["title"] = f"x-{name}"
        rc, out = run_check(with_entry(f, e))
        expect("NO_GIT_REF" not in out, f"a file in the folder but not in git ({name}) is not reported")

print('label "reminder" — the Hub repo\'s rules file in the reminder notebook (2026-10-03):')
REM = "ab4b7ccb"


def reminder_fake(t, sources, hand_titles=()):
    f = Fake(t, sources)
    f.REMINDER_NOTEBOOK_ID = REM

    def no_route(label):                       # as in the refresh tool: "reminder" is no route
        raise KeyError(f"Unknown route label: {label}")
    f.route_for_label = no_route
    f.activated = []
    f.activate_notebook = f.activated.append
    f._MANIFEST["NOTEBOOKLM_ACCOUNTED"] = []   # the fake lists the same sources for any notebook
    f._MANIFEST["NOTEBOOKLM_EXTERNAL"] = [{"path": str(f.rules), "label": "reminder",
                                           "title": "hub-CLAUDE.md", "hand_titles": list(hand_titles)}]
    # The reminder file list owns the vault's own rules file, a source titled "CLAUDE.md".
    (Path(t) / ".notebooklm-reminder-state.json").write_text(
        json.dumps({"CLAUDE.md": {"source_id": "vault-claude"}}))
    return f


with tempfile.TemporaryDirectory() as t:
    f = reminder_fake(t, [{"id": "vault-claude", "title": "CLAUDE.md"},
                          {"id": "hand-hub", "title": "hub-CLAUDE.md"},
                          {"id": "hand-hub-2", "title": "hub-CLAUDE.md"}])
    rc, out = run_check(f)
    expect(rc == 1 and "STALE\treminder\thub-CLAUDE.md\tnever synced" in out,
           "check resolves the reminder notebook (no route) and reports a copy never synced")
    c = quiet(ext.sync_externals, f, "reminder")
    ids = {s["id"] for s in f.sources}
    expect(f.activated == [REM], "it syncs into the reminder notebook")
    expect(c["adopted"] == 1 and "hand-hub" in ids and not f.uploaded,
           "the hand-kept copy with the managed title is adopted, not re-uploaded")
    expect("hand-hub-2" not in ids, "a second copy with the managed title is removed as a stray")
    expect("vault-claude" in ids, "the vault's own CLAUDE.md source is never touched")
    rc, out = run_check(f)
    expect(rc == 0, "and check is clean afterwards")
    f.rules.write_text("rules v2\n")
    c = quiet(ext.sync_externals, f, "reminder")
    ids = {s["id"] for s in f.sources}
    expect(c["replaced"] == 1 and f.uploaded == ["rules v2\n"] and "hand-hub" not in ids,
           "an edited file replaces the managed copy")
    expect([n for k, n in f.calls if k == "add"] == ["hub-CLAUDE.md"],
           'it is uploaded under the entry\'s title, never as "CLAUDE.md"')

print("a source another sync owns is never removed as a stray, whatever its title:")
with tempfile.TemporaryDirectory() as t:
    # Misconfigured on purpose: "CLAUDE.md" listed as a hand title in the reminder notebook,
    # where it is the title of the vault's own rules file.
    f = reminder_fake(t, [{"id": "vault-claude", "title": "CLAUDE.md"},
                          {"id": "hand-1", "title": "CLAUDE.md"}], hand_titles=["CLAUDE.md"])
    c, out = capture(ext.sync_externals, f, "reminder")
    ids = {s["id"] for s in f.sources}
    expect("vault-claude" in ids and ("delete", "vault-claude") not in f.calls,
           "the vault's CLAUDE.md (recorded by the reminder sync) is kept")
    expect("another sync owns it" in out, "and the run says why")
    expect("hand-1" not in ids, "a real stray with the same title is still removed")

print("Roll Call shows every finding kind (the block in limitless-preflight.sh):")
PF = HERE / "limitless-preflight.sh"
if not PF.exists():
    print("  skip limitless-preflight.sh is not beside this file")
else:
    pf_lines = PF.read_text().split("\n")
    a = next((i for i, l in enumerate(pf_lines) if "Sources outside the vault + an account of every source" in l), None)
    b = next((i for i in range(a or 0, len(pf_lines)) if "Join the capacity check backgrounded" in pf_lines[i]), None)
    expect(a is not None and b is not None, "the source-check block is found in limitless-preflight.sh")
    block = "\n".join(pf_lines[a:b]) if a is not None and b is not None else ""
    shell = "/bin/bash" if os.path.exists("/bin/bash") else "bash"          # macOS runs it on bash 3.2

    def roll_call(text, rc):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "tools").mkdir()
            (Path(t) / "tools" / "notebooklm_external.py").write_text("")
            script = ('set -u\nVAULT="$1"\nLIMITLESS_NB_ROLE=owner\n'
                      'ok() { printf "OK\\t%s\\n" "$1"; }\n'
                      'warn() { printf "WARN\\t%s\\t%s\\n" "$1" "${2:-}"; }\n'
                      'python3.11() { printf "%s" "$FAKE_OUT"; return "$FAKE_RC"; }\n' + block + "\n")
            p = subprocess.run([shell, "-c", script, "harness", t], capture_output=True, text=True,
                               env=dict(os.environ, FAKE_OUT=text, FAKE_RC=str(rc)))
            return p.returncode, p.stdout + p.stderr

    code, out = roll_call("", 0)
    expect(code == 0 and out.startswith("OK\tnotebooklm sources outside the vault are current"),
           "exit 0: one green line")
    code, out = roll_call("NO_GIT_REF\topenfirehouse\tx-CHANGELOG.md\twhy\n", 1)
    expect(code == 0 and "WARN\tnotebooklm openfirehouse: file(s) in git read from a folder" in out
           and "x-CHANGELOG.md" in out and '"git_ref": "origin/main"' in out and "cannot read" not in out,
           "NO_GIT_REF: a warning naming the file and the git_ref fix")
    code, out = roll_call("STALE\topenfirehouse\tx.md\tthe file changed since the last sync\n", 1)
    expect(code == 0 and "need a sync" in out and "--only openfirehouse" in out and "cannot read" not in out,
           "STALE: still a warning naming the refresh, as before")
    code, out = roll_call("SOMETHING_NEW\tx\ty\tz\n", 1)
    expect(code == 0 and "cannot read" in out, "an exit-1 finding Roll Call cannot read still warns — never silence")
    code, out = roll_call("ERROR\tcould not list notebook abc\n", 2)
    expect(code == 0 and "could not run" in out, "exit 2: 'could not run', as before")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    sys.exit(1)
print("all passed")
