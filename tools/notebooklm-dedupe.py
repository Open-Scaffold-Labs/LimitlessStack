#!/usr/bin/env python3.11
"""
Dedupe an active NotebookLM notebook.

Groups sources by title, keeps the most recently created copy of each,
deletes the older ones, and updates any state file that pointed at a
deleted source_id so it now points at the survivor.

The bug that creates these duplicates lives in `cmd_replace` inside
`notebooklm-wiki-refresh.py` — when `cmd_delete` returns False because
its post-check trips, the next call to `cmd_add` uploads a new copy
without removing the old one. Patch ships in the same commit as this
tool. Existing duplicates require this one-shot cleanup.

Usage:
    python3.11 tools/notebooklm-dedupe.py                           # dry-run, prints the plan
    python3.11 tools/notebooklm-dedupe.py --apply                   # actually delete
    python3.11 tools/notebooklm-dedupe.py --apply --state wiki      # also rewrite state file
    python3.11 tools/notebooklm-dedupe.py --notebook cdaa7a43       # specify notebook explicitly

Active notebook is taken from `notebooklm` CLI's current selection unless
--notebook is passed. State file is `tools/.notebooklm-<state>-state.json`.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def run_nb(args: list[str], capture: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["notebooklm", *args],
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def list_sources() -> list[dict]:
    r = run_nb(["source", "list", "--json"])
    if r.returncode != 0:
        print(f"source list failed: {r.stderr}", file=sys.stderr)
        sys.exit(2)
    data = json.loads(r.stdout)
    return data if isinstance(data, list) else data.get("sources", [])


def list_ids() -> set[str]:
    return {s.get("id") or s.get("source_id") for s in list_sources()}


def delete_source(source_id: str) -> bool:
    """Delete + verify gone. Returns True only if the source existed before
    and is gone after."""
    before = list_ids()
    if source_id not in before:
        print(f"    ! pre-check: source {source_id[:12]}… not in notebook (was already gone)")
        return False
    r = run_nb(["source", "delete", "-y", source_id])
    if r.returncode != 0:
        print(f"    ✗ delete returned {r.returncode}: {r.stderr.strip()}")
        return False
    after = list_ids()
    if source_id in after:
        print(f"    ✗ post-check: source still present after delete")
        return False
    return True


def find_dupes(sources: list[dict]) -> list[tuple[str, list[dict]]]:
    """Return [(title, [src1, src2, ...]), ...] for titles with >1 source."""
    by_title = defaultdict(list)
    for s in sources:
        title = s.get("title") or s.get("name") or s.get("display_name") or "?"
        by_title[title].append(s)
    out = []
    for title, group in sorted(by_title.items()):
        if len(group) > 1:
            # Sort newest first so group[0] is the survivor
            group.sort(key=lambda s: s.get("created_at") or "", reverse=True)
            out.append((title, group))
    return out


def remap_state(state_path: Path, id_remap: dict[str, str], dry_run: bool) -> int:
    """Rewrite state entries that pointed at a deleted source_id so they
    point at the survivor instead. Returns count of entries rewritten."""
    if not state_path.exists():
        print(f"  state file {state_path.name} doesn't exist, skipping remap")
        return 0
    state = json.loads(state_path.read_text())
    rewrites = 0
    for rel, entry in state.items():
        sid = entry.get("source_id")
        if sid and sid in id_remap:
            new_sid = id_remap[sid]
            print(f"  remap state[{rel!r}]  {sid[:12]}… → {new_sid[:12]}…")
            if not dry_run:
                state[rel]["source_id"] = new_sid
                # Clear verified_at so the next refresh will re-verify the
                # survivor's content instead of trusting a stale flag.
                state[rel].pop("verified_at", None)
            rewrites += 1
    if not dry_run and rewrites > 0:
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        print(f"  wrote {state_path.name} ({rewrites} entries remapped)")
    return rewrites


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", help="Notebook ID (default: currently selected)")
    ap.add_argument("--apply", action="store_true", help="Actually delete; without this, only prints the plan")
    ap.add_argument("--state", help="Route state label (e.g., 'wiki') to remap source_ids in tools/.notebooklm-<label>-state.json")
    args = ap.parse_args()

    if args.notebook:
        r = run_nb(["use", args.notebook])
        if r.returncode != 0:
            print(f"notebooklm use {args.notebook} failed: {r.stderr}", file=sys.stderr)
            sys.exit(2)

    sources = list_sources()
    print(f"Notebook has {len(sources)} sources")
    dupes = find_dupes(sources)
    if not dupes:
        print("No duplicates found.")
        return
    total_to_delete = sum(len(g) - 1 for _, g in dupes)
    print(f"{len(dupes)} duplicate groups; will delete {total_to_delete} source(s) (keeping the most recent of each).")
    print()

    id_remap: dict[str, str] = {}
    deleted_ids: set[str] = set()
    failed_ids: set[str] = set()

    for title, group in dupes:
        survivor = group[0]
        survivor_id = survivor.get("id")
        survivor_at = survivor.get("created_at", "?")
        print(f"  {title!r}")
        print(f"    KEEP    {survivor_id[:12]}… created {survivor_at}")
        for losing in group[1:]:
            losing_id = losing.get("id")
            losing_at = losing.get("created_at", "?")
            mode = "DELETE " if args.apply else "(dry)  "
            print(f"    {mode} {losing_id[:12]}… created {losing_at}")
            id_remap[losing_id] = survivor_id
            if args.apply:
                ok = delete_source(losing_id)
                if ok: deleted_ids.add(losing_id)
                else:  failed_ids.add(losing_id)
                # Tiny pause so consecutive deletes don't race the source list
                time.sleep(0.5)
        print()

    if args.state and args.apply:
        state_path = TOOLS / f".notebooklm-{args.state}-state.json"
        # Only remap entries for IDs we actually deleted (not the failures)
        applied_remap = {old: new for old, new in id_remap.items() if old in deleted_ids}
        remap_state(state_path, applied_remap, dry_run=False)
    elif args.state and not args.apply:
        state_path = TOOLS / f".notebooklm-{args.state}-state.json"
        print(f"(dry-run) would remap state file: {state_path.name}")
        remap_state(state_path, id_remap, dry_run=True)

    print()
    if args.apply:
        print(f"Done. Deleted {len(deleted_ids)} sources, {len(failed_ids)} failures.")
    else:
        print("Dry-run only — no deletions performed. Pass --apply to execute.")


if __name__ == "__main__":
    main()
