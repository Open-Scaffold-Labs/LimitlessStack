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
    python3.11 tools/notebooklm-dedupe.py --notebook cdaa7a43 --state wiki           # dry-run
    python3.11 tools/notebooklm-dedupe.py --notebook cdaa7a43 --state wiki --apply   # delete

    --state is REQUIRED for --apply (exit 2 without it). It names the route state
    file, which is the only thing that distinguishes a real duplicate from two
    different wiki pages that happen to share a basename — deleting the latter
    silently repoints one page's state entry at the other page's source, and every
    later refresh then reports it "in sync" while its content is absent. See
    find_dupes() for the ownership rule.

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

# The notebook every CLI call is pinned to. NEVER rely on `notebooklm use`
# context here: that context is a single shared file, so a concurrent process
# (the preflight's own 8-notebook sweep, the nightly self-heal, a second
# session) can repoint it BETWEEN our `use` and our `source list`. Observed
# live 2026-08-03 — a dedupe run targeting cdaa7a43 (40 sources) enumerated
# the OpenFirehouse notebook (14 sources) instead, because a background
# preflight moved the context mid-run. Deletes fail safe (the pre-check aborts
# on an id the listing doesn't contain) but the PLAN would have been computed
# against the wrong bucket. notebooklm-py's own skill doc says the same:
# "Always use explicit notebook ID in parallel workflows."
NOTEBOOK: str | None = None


def nb_args() -> list[str]:
    return ["--notebook", NOTEBOOK] if NOTEBOOK else []


def run_nb(args: list[str], capture: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["notebooklm", *args],
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def list_sources() -> list[dict]:
    r = run_nb(["source", "list", "--json", *nb_args()])
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
    r = run_nb(["source", "delete", "-y", source_id, *nb_args()])
    if r.returncode != 0:
        print(f"    ✗ delete returned {r.returncode}: {r.stderr.strip()}")
        return False
    after = list_ids()
    if source_id in after:
        print(f"    ✗ post-check: source still present after delete")
        return False
    return True


def load_claims(state_path: Path) -> dict[str, str]:
    """Reverse map source_id -> the wiki path that CLAIMS it, from a route
    state file. A claimed source is a live mirror of a real wiki page; an
    unclaimed one is a ghost left behind by the cmd_replace bug."""
    if not state_path or not state_path.exists():
        return {}
    state = json.loads(state_path.read_text())
    claims = {}
    for rel, entry in state.items():
        sid = entry.get("source_id") if isinstance(entry, dict) else None
        if sid:
            claims[sid] = rel
    return claims


def find_dupes(sources: list[dict], claims: dict[str, str] | None = None
               ) -> tuple[list[tuple[str, list[dict]]], list[tuple[str, list[str]]]]:
    """Return (dupe_groups, collisions).

    Sources are grouped by title, but a shared title is NOT proof of a
    duplicate: two DIFFERENT wiki pages can share a basename. This vault has
    exactly that — `wiki/index.md` and `wiki/app-creation-reminders/index.md`
    both upload as 'index.md'. Title-only grouping called them duplicates and
    the plan was to delete one and repoint its state entry at the other, which
    would have dropped a real page from the notebook AND left the state file
    asserting it was in sync (2026-08-03). Ownership, not title, decides.

    A source CLAIMED by a state entry is a live mirror of a distinct page.
    Two sources claimed by DIFFERENT paths are a filename collision, never a
    duplicate — those are returned separately as `collisions` (reported, never
    deleted). Only UNCLAIMED ghosts are deletable, and the claimed source is
    preferred as the survivor over merely-newest.
    """
    claims = claims or {}
    by_title = defaultdict(list)
    for s in sources:
        title = s.get("title") or s.get("name") or s.get("display_name") or "?"
        by_title[title].append(s)

    out, collisions = [], []
    for title, group in sorted(by_title.items()):
        if len(group) <= 1:
            continue
        group.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        claimed = [s for s in group if claims.get(s.get("id"))]
        unclaimed = [s for s in group if not claims.get(s.get("id"))]
        owners = {claims[s["id"]] for s in claimed}

        if len(owners) > 1:
            # Distinct pages sharing a basename. Report; never touch.
            collisions.append((title, sorted(owners)))
            if not unclaimed:
                continue
            # Ghosts alongside a collision are ambiguous — we cannot tell which
            # page a ghost belonged to, so we refuse to guess.
            collisions[-1] = (title, sorted(owners) + [f"+{len(unclaimed)} unclaimed (not touched — owner ambiguous)"])
            continue

        if not unclaimed:
            # Every copy is claimed by the same single path: a true duplicate.
            out.append((title, group))
            continue

        # Prefer the claimed source as survivor; delete the ghosts.
        survivor = claimed[0] if claimed else group[0]
        losers = [s for s in group if s is not survivor]
        out.append((title, [survivor] + losers))
    return out, collisions


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

    global NOTEBOOK
    if args.notebook:
        # Pin every subsequent CLI call to this id via --notebook. We do NOT
        # call `notebooklm use`: that mutates shared context another process
        # can overwrite mid-run (see the NOTEBOOK comment above).
        NOTEBOOK = args.notebook
    else:
        # No id given: we fall back to whatever `use` context is set, which is
        # race-prone. Say so rather than silently trusting it.
        print("! No --notebook given; using shared CLI context, which a concurrent")
        print("  process can repoint mid-run. Pass --notebook <id> to pin it.")

    sources = list_sources()
    print(f"Notebook {NOTEBOOK or '(context)'} has {len(sources)} sources")
    state_path = TOOLS / f".notebooklm-{args.state}-state.json" if args.state else None
    claims = load_claims(state_path) if state_path else {}
    if not claims:
        print("! No route state loaded — cannot tell a real duplicate from two")
        print("  different pages sharing a filename. Pass --state <label> (e.g. wiki).")
        if args.apply:
            print("  Refusing to --apply without an ownership map.", file=sys.stderr)
            sys.exit(2)

    dupes, collisions = find_dupes(sources, claims)

    for title, owners in collisions:
        print(f"  {title!r}: filename collision, NOT duplicates — left alone")
        for o in owners:
            print(f"    · {o}")
    if collisions:
        print()

    if not dupes:
        print("No duplicates found." if not collisions
              else "No true duplicates found (collisions above are distinct pages).")
        return
    total_to_delete = sum(len(g) - 1 for _, g in dupes)
    print(f"{len(dupes)} duplicate groups; will delete {total_to_delete} source(s) (keeping the claimed/most-recent of each).")
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
