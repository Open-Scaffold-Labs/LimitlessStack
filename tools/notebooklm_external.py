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
    Exit 0 clean, 1 findings, 2 could not check.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
    notebook_id, _, display = rf.route_for_label(label)
    state_path = _state_dir(rf) / STATE_NAME
    state = _load(state_path)
    rf.activate_notebook(notebook_id)
    # .resolve(): on macOS the temp dir sits under /var, a symlink to /private/var, and the
    # notebooklm CLI refuses to upload any path with a symlink in it (found 2026-09-25).
    stage = Path(tempfile.mkdtemp(prefix="nblm-external-")).resolve()
    try:
        for e in mine:
            title, path = e["title"], e["path"]
            if not os.path.isfile(path):
                print(f"  [{display}] ? external {title}: {path} is not on this machine — skipped")
                counts["skipped"] += 1
                continue
            sha = _sha(path)
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
                shutil.copyfile(path, staged)
                if dry_run:
                    print(f"  [{display}] ~ would sync external {title}")
                else:
                    old = entry.get("source_id") if entry and entry.get("source_id") in live_ids else None
                    if not old:
                        # Adopt an untracked copy already titled with the managed title,
                        # if (and only if) its content matches the file on disk.
                        same = [s for s in live if (s.get("title") or "") == title]
                        for s in same:
                            if rf.cmd_verify_content(_sid(s), staged, wait_retries=2):
                                old = _sid(s)
                                break
                        if old and (not entry or entry.get("source_id") != old):
                            state[title] = {"path": e["path"], "notebook": notebook_id,
                                            "source_id": old, "sha256": sha,
                                            "verified_at": time.time()}
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
                            state[title] = {"path": e["path"], "notebook": notebook_id,
                                            "source_id": sid, "sha256": sha,
                                            "verified_at": time.time()}
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
            for s in live:
                t, sid = s.get("title") or "", _sid(s)
                if sid == entry["source_id"] or (t not in e["hand_titles"] and t != title):
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

    for e in ext:
        nb, _, _ = rf.route_for_label(e["label"])
        title = e["title"]
        if not os.path.isfile(e["path"]):
            continue                      # not on this machine — the sync skips it too
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
        elif entry.get("sha256") != _sha(e["path"]):
            why = "the file changed since the last sync"
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
