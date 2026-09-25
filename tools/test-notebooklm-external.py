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

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    sys.exit(1)
print("all passed")
