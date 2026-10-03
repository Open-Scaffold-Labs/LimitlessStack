#!/usr/bin/env python3
"""NotebookLM sources that live OUTSIDE the vault, and an account of every source.

Added 2026-09-25 (Matt's greenlight). Why this exists: the OpenFirehouse notebook held
14 of 38 sources that sessions had uploaded BY HAND — the repo's rules file and
changelog every session, plus one-off copies of handoffs, a July task list and a July
copy of the wiki log. Nothing recorded which copy was current, so a session that
uploaded an old copy (it happened on 2026-09-25) left two, and the duplicate cleaner
keeps the NEWEST copy, which need not be the current one. Stale sources then fed the
answer to every OpenFirehouse session's first NotebookLM question.

Two jobs, both driven by the vault's .limitless-project.py (owner only — the paths are
the vault owner's machine and the notebooks are the owner's):

  NOTEBOOKLM_EXTERNAL = [ {"path": "~/...", "label": "<route label>", "title": "<distinct title>",
                           "hand_titles": ["CLAUDE.md"]} ]
      Files kept current by the refresh tool. Each is uploaded under its own distinct
      title, so a hand upload (which NotebookLM titles with the bare filename) can never
      be mistaken for the managed copy. Re-uploaded only when the CONTENT changes (sha256).
      After the managed copy is verified, any copy titled with one of `hand_titles` is a
      stray and is removed (its text is saved first — see NOTEBOOKLM_REMOVED_BACKUP).

      Optional "git_ref": "origin/main" — for a file kept in a git repository: send the
      file as it is on that branch (fetched once per run), not the copy in the folder. The
      path then only says which repository and file. Added 2026-10-03: the OpenFirehouse
      CHANGELOG was read from a folder no session brought up to date, so for two days the
      notebook missed every new entry while each run reported the file "unchanged". If the
      fetch fails, the branch as last fetched is used and the run says so — never the
      folder. A file the branch does not have is a failure, never a quiet skip.
      "git_ref": None reads the folder ON PURPOSE. A file committed in git with neither is
      reported by --check (NO_GIT_REF), so a new entry cannot fall behind unnoticed.

      "label": "reminder" puts the file in the curated reminder notebook rather than a
      wiki route's notebook. Added 2026-10-03 for the Hub repo's rules file, kept there as
      "hub-CLAUDE.md": it was maintained by hand, nothing checked it, and it fell 11 days
      behind (09-22 → 10-03). It could not go in the reminder file list because that list
      uploads by filename and "CLAUDE.md" is the vault's own source in that notebook; this
      path uploads under the entry's title. A source another sync records as its own is
      never removed as a stray, whatever its title.

  NOTEBOOKLM_FROZEN = { "<notebook id>": ["<title>", ...] }
      Sources kept on purpose that never change (dated specs, handoffs).

  NOTEBOOKLM_ACCOUNTED = ["<notebook id>", ...]
      Notebooks where EVERY source must be managed by the refresh tool (wiki routes or the
      external list) or listed as frozen. `--check` reports anything else.

Runs two ways:
  * from notebooklm-wiki-refresh.py (`--only <label>` or a full run) — sync_externals();
  * standalone `python3.11 tools/notebooklm_external.py --check` — read-only, for Roll Call.
    Prints one line per finding:  STALE<TAB>label<TAB>title<TAB>why   (the refresh fixes it)
                                  UNACCOUNTED<TAB>notebook<TAB>source id<TAB>title
                                  NO_GIT_REF<TAB>label<TAB>title<TAB>why   (a person sets git_ref)
    Exit 0 clean, 1 findings, 2 could not check.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE_NAME = ".notebooklm-external-state.json"


# ── config ────────────────────────────────────────────────────────────────
def config(manifest: dict) -> tuple[list[dict], dict, list[str], str]:
    ext = []
    for e in manifest.get("NOTEBOOKLM_EXTERNAL", []) or []:
        d = dict(e)
        d["path"] = os.path.expanduser(d["path"])
        d.setdefault("hand_titles", [])
        ext.append(d)
    frozen = {k: list(v) for k, v in (manifest.get("NOTEBOOKLM_FROZEN", {}) or {}).items()}
    accounted = list(manifest.get("NOTEBOOKLM_ACCOUNTED", []) or [])
    backup = os.path.expanduser(manifest.get("NOTEBOOKLM_REMOVED_BACKUP", "") or "")
    return ext, frozen, accounted, backup


def _role(rf) -> str:
    # The per-person notebook swap (tools/limitless_member.py) sets rf.MEMBER; a vault
    # without it is a single-owner vault.
    return (getattr(rf, "MEMBER", None) or {"role": "owner"}).get("role", "owner")


def _state_dir(rf) -> Path:
    return getattr(rf, "STATE_DIR", None) or rf.TOOLS


REMINDER_LABEL = "reminder"


def _notebook_for(rf, label: str) -> tuple[str, str]:
    """(notebook id, display name) for an entry's label: a wiki route's notebook, or the
    curated reminder notebook for "reminder" (not a route — route_for_label() rejects it)."""
    if label == REMINDER_LABEL:
        return rf.REMINDER_NOTEBOOK_ID, REMINDER_LABEL
    nbid, _, display = rf.route_for_label(label)
    return nbid, display


def _owned_elsewhere(rf) -> set[str]:
    """Source ids that another sync (a wiki route, the reminder file list) records as its
    own. Never removed as strays: in the reminder notebook the vault's own rules file is a
    source titled "CLAUDE.md", and a title alone must never decide that it goes."""
    ids: set[str] = set()
    for p in _state_dir(rf).glob(".notebooklm-*-state.json"):
        if p.name == STATE_NAME:
            continue
        for v in _load(p).values():
            if isinstance(v, dict) and v.get("source_id"):
                ids.add(v["source_id"])
    return ids


# ── what an entry's notebook copy should say (2026-10-03) ─────────────────
class Unreadable(Exception):
    """The configured source could not be read. Never answered with the folder's copy."""


def _git(cwd: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")      # never wait on a password prompt
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, timeout=timeout, env=env)


def _repo_of(path: str) -> tuple[str, str] | None:
    """(repository root, the file's path inside it), or None when the file's folder is not
    a git working tree on this machine."""
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        return None
    try:
        r = _git(folder, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    top = r.stdout.decode().strip()
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(top))
    return top, rel.replace(os.sep, "/")


def _tracked(path: str) -> bool:
    """True when the file is committed in a git repository on this machine (an ignored or
    untracked file, like the OpenFirehouse rules file, is not)."""
    repo = _repo_of(path)
    if repo is None:
        return False
    top, rel = repo
    try:
        return _git(top, "ls-files", "--error-unmatch", "--", rel).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _fetch(top: str, ref: str, fetched: dict) -> str | None:
    """Fetch the branch behind `ref` (e.g. origin/main) once per run.
    Returns None when the fetch worked, otherwise what went wrong."""
    key = (os.path.realpath(top), ref)
    if key not in fetched:
        remote, _, branch = ref.partition("/")
        try:
            r = _git(top, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", remote, branch)
            lines = r.stderr.decode(errors="replace").strip().splitlines()
            fetched[key] = None if r.returncode == 0 else (lines[-1] if lines else "git fetch failed")
        except (OSError, subprocess.TimeoutExpired) as exc:
            fetched[key] = str(exc)
    return fetched[key]


def _content(e: dict, fetched: dict) -> tuple[bytes, str | None, str | None] | None:
    """(content, commit, note) for entry `e`, or None when its file is not on this machine
    (the sync skips it and the check ignores it, as before).

    Without "git_ref": the file in the folder, exactly as before. With it: the file as it
    is on that branch — `commit` is the commit read, and `note` says so when the fetch
    failed and the branch as last fetched was used. Raises Unreadable when the branch or
    the file on it is missing."""
    path, ref = e["path"], e.get("git_ref")
    if not ref:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return fh.read(), None, None
    repo = _repo_of(path)
    if repo is None:
        return None
    top, rel = repo
    why = _fetch(top, ref, fetched)
    note = f"could not fetch {ref} ({why}) — using {ref} as last fetched" if why else None
    try:
        c = _git(top, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        commit = c.stdout.decode().strip() if c.returncode == 0 else ""
        if not commit:
            raise Unreadable(f"{ref} does not exist in {top}")
        b = _git(top, "show", f"{commit}:{rel}")      # the commit, so both reads agree
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unreadable(f"git could not read it ({exc})")
    if b.returncode != 0:
        raise Unreadable(f"{rel} is not on {ref}")
    return b.stdout, commit, note


def _record(e: dict, notebook_id: str, sid: str, sha: str, commit: str | None) -> dict:
    rec = {"path": e["path"], "notebook": notebook_id, "source_id": sid, "sha256": sha,
           "verified_at": time.time()}
    if commit:
        rec["git_ref"], rec["git_commit"] = e["git_ref"], commit
    return rec


def _load(state_path: Path) -> dict:
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return {}


def _save(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def _sources(rf, notebook_id: str) -> list[dict] | None:
    r = rf.run_nb(["source", "list", "--json", "--notebook", notebook_id])
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except Exception:
        return None
    return data if isinstance(data, list) else data.get("sources", [])


def _sid(s: dict) -> str:
    return s.get("id") or s.get("source_id") or ""


def _backup_text(rf, notebook_id: str, sid: str, title: str, backup_dir: str) -> bool:
    """Save a source's indexed text before it is removed. Returns False if it could not."""
    if not backup_dir:
        return False
    r = rf.run_nb(["source", "fulltext", sid, "--notebook", notebook_id, "--json"])
    try:
        content = json.loads(r.stdout).get("content", "")
    except Exception:
        content = ""
    if not content:
        return False
    day = time.strftime("%Y-%m-%d")
    out = Path(backup_dir) / day
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in title)
    (out / f"{sid[:8]}-{safe}.txt").write_text(content)
    return True


# ── sync (called by the refresh tool) ─────────────────────────────────────
def sync_externals(rf, label: str, dry_run: bool = False, force: bool = False) -> dict:
    """Keep every NOTEBOOKLM_EXTERNAL file routed to `label` current in its notebook."""
    counts = {"added": 0, "replaced": 0, "adopted": 0, "unchanged": 0, "skipped": 0,
              "failed": 0, "strays_removed": 0}
    if _role(rf) != "owner":
        return counts
    ext, _frozen, _acc, backup = config(rf._MANIFEST)
    mine = [e for e in ext if e.get("label") == label]
    if not mine:
        return counts
    notebook_id, display = _notebook_for(rf, label)
    state_path = _state_dir(rf) / STATE_NAME
    state = _load(state_path)
    rf.activate_notebook(notebook_id)
    # .resolve(): on macOS the temp dir sits under /var, a symlink to /private/var, and the
    # notebooklm CLI refuses to upload any path with a symlink in it (found 2026-09-25).
    stage = Path(tempfile.mkdtemp(prefix="nblm-external-")).resolve()
    fetched: dict = {}
    try:
        for e in mine:
            title, path = e["title"], e["path"]
            try:
                got = _content(e, fetched)
            except Unreadable as exc:
                print(f"  [{display}] ✗ external {title}: {exc} — nothing changed")
                counts["failed"] += 1
                continue
            if got is None:
                print(f"  [{display}] ? external {title}: {path} is not on this machine — skipped")
                counts["skipped"] += 1
                continue
            content, commit, note = got
            if note:
                print(f"  [{display}] ! external {title}: {note}")
            sha = hashlib.sha256(content).hexdigest()
            entry = state.get(title)
            live = _sources(rf, notebook_id)
            if live is None:
                print(f"  [{display}] ✗ external {title}: could not list the notebook — nothing changed")
                counts["failed"] += 1
                continue
            live_ids = {_sid(s) for s in live}
            if entry and entry.get("sha256") == sha and entry.get("source_id") in live_ids \
                    and entry.get("verified_at") and not force:
                counts["unchanged"] += 1
            else:
                staged = stage / title
                staged.write_bytes(content)
                if dry_run:
                    src = f" (from {e['git_ref']} at {commit[:7]})" if commit else ""
                    print(f"  [{display}] ~ would sync external {title}{src}")
                else:
                    old = entry.get("source_id") if entry and entry.get("source_id") in live_ids else None
                    if not old:
                        # Adopt an untracked copy already titled with the managed title,
                        # if (and only if) its content matches the content being synced.
                        same = [s for s in live if (s.get("title") or "") == title]
                        for s in same:
                            if rf.cmd_verify_content(_sid(s), staged, wait_retries=2):
                                old = _sid(s)
                                break
                        if old and (not entry or entry.get("source_id") != old):
                            state[title] = _record(e, notebook_id, old, sha, commit)
                            _save(state_path, state)
                            print(f"  [{display}] ✓ external {title}: adopted existing copy {old[:8]}")
                            counts["adopted"] += 1
                            entry = state[title]
                    if not (entry and entry.get("source_id") == old and entry.get("sha256") == sha
                            and entry.get("verified_at")):
                        print(f"  [{display}] ~ {'replace' if old else 'add'} external {title}")
                        if old:
                            sid, verified, _gone = rf.cmd_replace(staged, old)
                        else:
                            sid = rf.cmd_add(staged)
                            verified = bool(sid) and rf.cmd_verify_content(sid, staged)
                        if sid and not verified:
                            sid, verified, _gone = rf.heal_verify(staged, sid)
                        if sid and verified:
                            state[title] = _record(e, notebook_id, sid, sha, commit)
                            _save(state_path, state)
                            counts["replaced" if old else "added"] += 1
                            print(f"    ✓ content verified in notebook")
                        else:
                            counts["failed"] += 1
                            what = "upload failed" if not sid else "uploaded but NOT verified"
                            print(f"    ✗ external {title}: {what} — state unchanged, next run retries")
                            continue
            # Strays: hand uploads carry the bare filename. Remove them only once the
            # managed copy is verified, and save their text first.
            entry = state.get(title)
            if dry_run or not (entry and entry.get("verified_at")):
                continue
            live = _sources(rf, notebook_id) or []
            owned = _owned_elsewhere(rf)
            for s in live:
                t, sid = s.get("title") or "", _sid(s)
                if sid == entry["source_id"] or (t not in e["hand_titles"] and t != title):
                    continue
                if sid in owned:
                    print(f"  [{display}] ! {t} ({sid[:8]}) kept — another sync owns it")
                    continue
                if not _backup_text(rf, notebook_id, sid, t, backup):
                    print(f"  [{display}] ! stray {t} ({sid[:8]}) kept — its text could not be saved first")
                    continue
                if rf.cmd_delete(sid):
                    counts["strays_removed"] += 1
                    print(f"  [{display}] - removed stray copy {t} ({sid[:8]}); text saved under {backup}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print(f"[{display}] EXTERNAL DONE  " + "  ".join(f"{k}: {v}" for k, v in counts.items()))
    return counts


# ── check (read-only, for Roll Call) ──────────────────────────────────────
def check(rf) -> int:
    if _role(rf) != "owner":
        print("SKIP\tnot the vault owner — external files and accounting are the owner's")
        return 0
    ext, frozen, accounted, _backup = config(rf._MANIFEST)
    if not ext and not accounted:
        return 0
    state = _load(_state_dir(rf) / STATE_NAME)
    findings = 0
    listings: dict[str, list[dict]] = {}

    def listing(nb: str):
        if nb not in listings:
            got = _sources(rf, nb)
            if got is None:
                return None
            listings[nb] = got
        return listings[nb]

    fetched: dict = {}
    for e in ext:
        nb, _ = _notebook_for(rf, e["label"])
        title = e["title"]
        try:
            got = _content(e, fetched)
        except Unreadable as exc:
            print(f"ERROR\tcould not read {title}: {exc}")
            return 2
        if got is None:
            continue                      # not on this machine — the sync skips it too
        if "git_ref" not in e and _tracked(e["path"]):
            print(f"NO_GIT_REF\t{e['label']}\t{title}\tit is in git but read from the folder, "
                  "which can fall behind GitHub")
            findings += 1
        live = listing(nb)
        if live is None:
            print(f"ERROR\tcould not list notebook {nb[:8]}")
            return 2
        entry = state.get(title) or {}
        ids = {_sid(s) for s in live}
        why = None
        if not entry:
            why = "never synced"
        elif entry.get("source_id") not in ids:
            why = "its notebook copy is missing"
        elif entry.get("sha256") != hashlib.sha256(got[0]).hexdigest():
            why = (f"it changed on {e['git_ref']} since the last sync" if e.get("git_ref")
                   else "the file changed since the last sync")
        elif not entry.get("verified_at"):
            why = "the last upload was not verified"
        elif any((s.get("title") or "") in e["hand_titles"] for s in live):
            why = "a hand-uploaded copy is in the notebook"
        if why:
            print(f"STALE\t{e['label']}\t{title}\t{why}")
            findings += 1

    for nb in accounted:
        full = next((r[1] for r in rf.NOTEBOOK_ROUTES if r[1].startswith(nb)), nb)
        live = listing(full)
        if live is None:
            print(f"ERROR\tcould not list notebook {nb[:8]}")
            return 2
        owned = set()
        for r in rf.NOTEBOOK_ROUTES:
            if r[1] == full and r[2]:
                owned |= {v.get("source_id") for v in _load(rf.state_file_for(r[2])).values()
                          if isinstance(v, dict)}
        owned |= {v.get("source_id") for v in state.values() if isinstance(v, dict)}
        keep_titles = set(frozen.get(nb, [])) | set(frozen.get(full, []))
        managed_titles = {e["title"] for e in ext}
        hand_titles = {t for e in ext for t in e["hand_titles"]}
        for s in live:
            t, sid = s.get("title") or "", _sid(s)
            if sid in owned or t in keep_titles:
                continue
            if t in managed_titles or t in hand_titles:
                continue                  # reported (and fixed) by the STALE pass above
            print(f"UNACCOUNTED\t{nb[:8]}\t{sid}\t{t}")
            findings += 1
    return 1 if findings else 0


def _load_refresh():
    import importlib.util
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("_nblm_refresh", here / "notebooklm-wiki-refresh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check(_load_refresh()))
    print(__doc__)
    sys.exit(0)
