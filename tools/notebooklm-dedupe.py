#!/usr/bin/env python3.11
"""
Dedupe an active NotebookLM notebook.

Groups sources by title, keeps the newest READY copy of each, deletes the
older ones, and updates any state file that pointed at a deleted source_id
so it now points at the survivor.

WHERE DUPLICATES COME FROM (current, as of 2026-08-03). `cmd_replace` in
`notebooklm-wiki-refresh.py` runs ADD → verify → delete-old-by-id. That
ordering is deliberate: deleting first turned a source-cap failure into
permanent data loss and cost 17 sources in the 2026-07-26..29 window. The
trade is that an interrupted replace leaves BOTH copies — a duplicate,
which is the recoverable direction, and which this tool cleans up.

⚠ THE CONSEQUENCE THAT BIT US TWICE. `_checkpoint()` writes state only after
`cmd_replace` RETURNS, so an interrupted replace leaves the newest copy
UNCLAIMED and its stale predecessor CLAIMED. Survivor selection therefore
keys on recency + readiness, never on the claim; the claim decides only
OWNERSHIP (which page a source mirrors), which is what stops two distinct
pages sharing a basename from being "deduped" into one. See find_dupes.

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
    state file.

    A claim proves OWNERSHIP — which wiki page a source mirrors. It does NOT
    prove CURRENCY, and conflating the two is what made this tool recommend
    deleting live content (see find_dupes).

    ⚠ This used to read "an unclaimed one is a ghost left behind by the
    cmd_replace bug." That was true while cmd_replace was DELETE-first: the
    leftover really was junk. cmd_replace was inverted to ADD-before-DELETE on
    2026-08-03, and `_checkpoint()` writes state only AFTER cmd_replace returns
    — so an interrupted replace now leaves the FRESHEST source unclaimed and the
    stale predecessor claimed. Unclaimed means "state has not caught up yet",
    which is the opposite of junk. Corrected 2026-08-20."""
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
    """Return (dupe_groups, reported).

    `reported` is the "print it, never delete it" channel and its entries are
    (title, reason, details). The reason field exists because that channel now
    carries TWO different refusals — a filename collision and a group with no
    ready copy — and the printer used to hardcode "filename collision" over
    whatever arrived (caught in review 2026-08-20, before it shipped).


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
    deleted). That ownership rule is the IDENTITY guarantee and is unchanged.

    ⚠ SURVIVOR SELECTION CHANGED 2026-08-20 — the claim decides IDENTITY, never
    CURRENCY. This function used to end "the claimed source is preferred as the
    survivor over merely-newest", which silently inverted when cmd_replace was
    changed to ADD-before-DELETE on 2026-08-03:

      * DELETE-first (pre 08-03): old removed, new added. A leftover unclaimed
        source was junk from a failed add. Preferring the claimed one was RIGHT.
      * ADD-first (current): new added, THEN old removed — and `_checkpoint()`
        writes state only after cmd_replace RETURNS. Interrupt in between and
        the unclaimed source is the NEWEST CONTENT while the claimed one is its
        stale predecessor. Preferring the claimed one now deletes live content
        and repoints state at the stale copy, after which every later refresh
        reports "in sync" forever.

    Observed twice before it was traced: team-tasks.md on 2026-08-18
    (wiki/log.md:7591 — diagnosed as "always re-run the refresh after a dedupe",
    a workaround for the symptom), and log.md on 2026-08-20, where the dry-run
    proposed keeping a copy 3,677 chars SHORT of the one it wanted to delete.

    So within a single-owner group the survivor is the newest READY source.
    Readiness matters: a still-indexing upload can win on created_at while
    holding nothing, and deleting the only ready copy in its favour would be
    the same data loss by a different route. A group with NO ready source is
    refused rather than guessed at.
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
            collisions.append((title, "filename collision", sorted(owners)))
            if not unclaimed:
                continue
            # Ghosts alongside a collision are ambiguous — we cannot tell which
            # page a ghost belonged to, so we refuse to guess.
            collisions[-1] = (title, "filename collision",
                              sorted(owners) + [f"+{len(unclaimed)} unclaimed (not touched — owner ambiguous)"])
            continue

        # ── Survivor = newest READY source (2026-08-20) ───────────────────
        # `group` is already sorted newest-first. Both former branches (all-
        # claimed, and claimed+ghosts) now resolve the same way, because the
        # claim never carried currency information in either of them.
        statuses = [str(s.get("status") or "").lower() for s in group]
        if any(statuses):
            ready = [s for s in group
                     if str(s.get("status") or "").lower() == "ready"]
            if not ready:
                # Every copy still indexing, or errored. Deleting any of them
                # could destroy the only recoverable content. Report, never act.
                # NOTE this rides the same "reported, never deleted" channel as
                # a filename collision but is NOT one — hence the explicit
                # reason field, added after the first draft pushed it in here
                # and would have printed "filename collision" over it.
                collisions.append((title, "no ready copy", [
                    f"{len(group)} copies, statuses: "
                    f"{', '.join(sorted(set(statuses)))} — refusing to choose a survivor"]))
                continue
        else:
            # No source reported a status at all. Don't invent readiness —
            # fall back to newest-overall and say so at print time.
            ready = group

        survivor = ready[0]
        losers = [s for s in group if s is not survivor]
        # Flag the case this fix exists for: the state file claims a source
        # that is NOT the survivor. Expected after an interrupted add-first
        # replace; remap_state repoints it, and the caller is told to re-verify.
        survivor["_claim_moved"] = bool(
            claimed and claims.get(claimed[0].get("id")) and claimed[0] is not survivor
        )
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

    for title, reason, owners in collisions:
        if reason == "filename collision":
            print(f"  {title!r}: filename collision, NOT duplicates — left alone")
        else:
            print(f"  {title!r}: {reason} — left alone, nothing deleted")
        for o in owners:
            print(f"    · {o}")
    if collisions:
        print()

    if not dupes:
        print("No duplicates found." if not collisions
              else "No true duplicates found (collisions above are distinct pages).")
        return
    total_to_delete = sum(len(g) - 1 for _, g in dupes)
    print(f"{len(dupes)} duplicate groups; will delete {total_to_delete} source(s) (keeping the NEWEST READY copy of each).")
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
        if survivor.pop("_claim_moved", False):
            # The state file claimed a DIFFERENT copy. Normal after an
            # interrupted add-before-delete replace; remap_state repoints it.
            # Said out loud because the old code silently kept the claimed one
            # and that is exactly how live content got proposed for deletion.
            print("      ↳ state claimed a different copy; the claim moves to this one")
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
        if deleted_ids:
            # wiki/log.md:7591 (2026-08-18) recorded this as the standing
            # mitigation and it was never wired into the tool that needs it:
            # a survivor can be behind the file on disk, and the state entry
            # this run just repointed carries no verified_at. Say it here so
            # nobody has to remember it.
            print()
            print("NEXT — do not skip: a survivor is the newest copy in the NOTEBOOK,")
            print("which is not necessarily current with the file on disk. Re-verify:")
            lbl = args.state or "<label>"
            print(f"  python3.11 tools/notebooklm-wiki-refresh.py --only {lbl} --verify-existing")
            print("(no uploads; backfills verified_at). Only refresh for real if that reports a gap.")
    else:
        print("Dry-run only — no deletions performed. Pass --apply to execute.")


if __name__ == "__main__":
    main()
