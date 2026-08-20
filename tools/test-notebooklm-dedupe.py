#!/usr/bin/env python3.11
"""
Regression fence for notebooklm-dedupe.find_dupes survivor selection.

WHY THIS FILE EXISTS. On 2026-08-20 the deduper's dry-run proposed KEEPING a
`log.md` source 3,677 characters shorter than the one it proposed DELETING, and
repointing the state file at the shorter copy — after which every later check
would report "in sync" over a notebook missing the newest session's entry.

The cause was not a typo. `survivor = claimed[0]` encoded "unclaimed == ghost",
which was TRUE while `cmd_replace` deleted before adding. When cmd_replace was
inverted to ADD-before-DELETE on 2026-08-03 (to stop a source-cap failure from
destroying data), an interrupted replace began leaving the NEWEST copy unclaimed
and the STALE one claimed — because `_checkpoint()` writes state only after
cmd_replace returns. One fix silently inverted another module's assumption, and
nothing failed. The same symptom had already been seen on team-tasks.md
(wiki/log.md:7591, 2026-08-18) and was written off as "always re-run the refresh
after a dedupe" — a workaround aimed at the symptom.

These tests are the thing that was missing. Run:
    python3.11 tools/test-notebooklm-dedupe.py
Exit 0 = pass, 1 = fail. It is meant to FAIL if anyone restores the old rule;
`--prove` demonstrates that rather than asserting it.
"""
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "nbdedupe", TOOLS / "notebooklm-dedupe.py")
nbd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nbd)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILURES.append(name)


def src(sid, created, status="ready", title="log.md"):
    return {"id": sid, "title": title, "created_at": created, "status": status}


# ── 1. THE REAL 2026-08-20 CASE ───────────────────────────────────────────
# Interrupted add-before-delete: newest copy exists but state still claims the
# predecessor. The survivor must be the NEWEST, not the claimed one.
def test_interrupted_replace():
    group = [src("new050e", "2026-08-20T15:32:29+00:00"),
             src("old8152", "2026-08-20T15:14:19+00:00")]
    claims = {"old8152": "wiki/log.md"}          # state lags reality
    dupes, collisions = nbd.find_dupes(group, claims)
    check("interrupted replace -> one dupe group", len(dupes) == 1, f"got {len(dupes)}")
    if not dupes:
        return
    survivor = dupes[0][1][0]
    check("survivor is the NEWEST copy, not the state-claimed one",
          survivor["id"] == "new050e",
          f"survivor={survivor['id']} (old behaviour would pick old8152)")
    check("no collision reported for a single-owner group", not collisions)


# ── 2. THE IDENTITY GUARANTEE — must be untouched by the fix ──────────────
# Two DIFFERENT pages sharing a basename. Never a duplicate, never deleted.
# This is the 2026-08-03 guard that stopped a real page being dropped.
def test_basename_collision_never_deleted():
    group = [src("a1", "2026-08-20T10:00:00+00:00", title="index.md"),
             src("b2", "2026-08-19T10:00:00+00:00", title="index.md")]
    claims = {"a1": "wiki/index.md",
              "b2": "wiki/app-creation-reminders/index.md"}
    dupes, collisions = nbd.find_dupes(group, claims)
    check("distinct pages sharing a basename are NOT dupes", not dupes,
          f"got {len(dupes)} dupe group(s) — this would delete a live page")
    check("collision is reported instead", len(collisions) == 1)
    check("and it is labelled a filename collision",
          collisions and collisions[0][1] == "filename collision",
          f"reason={collisions[0][1] if collisions else None!r}")


# ── 3. All copies claimed by ONE path — newest still wins ────────────────
def test_same_owner_two_claims():
    group = [src("n1", "2026-08-20T12:00:00+00:00"),
             src("n2", "2026-08-20T09:00:00+00:00")]
    claims = {"n1": "wiki/log.md", "n2": "wiki/log.md"}
    dupes, _ = nbd.find_dupes(group, claims)
    check("same-owner duplicates -> newest survives",
          dupes and dupes[0][1][0]["id"] == "n1")


# ── 4. READINESS — never delete a ready copy for a still-indexing one ────
def test_newest_but_not_ready():
    group = [src("indexing", "2026-08-20T15:32:00+00:00", status="processing"),
             src("ready1", "2026-08-20T15:14:00+00:00", status="ready")]
    claims = {"ready1": "wiki/log.md"}
    dupes, _ = nbd.find_dupes(group, claims)
    check("newest-but-unready loses to the newest READY copy",
          dupes and dupes[0][1][0]["id"] == "ready1",
          "deleting the only ready copy is the same data loss by another route")


def test_none_ready_is_refused():
    group = [src("p1", "2026-08-20T15:32:00+00:00", status="processing"),
             src("p2", "2026-08-20T15:14:00+00:00", status="error")]
    claims = {"p1": "wiki/log.md"}
    dupes, collisions = nbd.find_dupes(group, claims)
    check("a group with NO ready copy is refused, not guessed", not dupes,
          f"got {len(dupes)} — would have deleted an unrecoverable copy")
    check("and it is reported", len(collisions) == 1)
    # Regression fence for a bug caught in review, not in production: the
    # refusal rode the collision channel and would have printed "filename
    # collision" as its explanation. A wrong reason is its own defect.
    check("and it is NOT mislabelled a filename collision",
          collisions and collisions[0][1] == "no ready copy",
          f"reason={collisions[0][1] if collisions else None!r}")


# ── 5. Missing status field -> fall back to newest, don't invent readiness ─
def test_missing_status_falls_back_to_newest():
    group = [{"id": "x1", "title": "log.md", "created_at": "2026-08-20T15:32:00+00:00"},
             {"id": "x2", "title": "log.md", "created_at": "2026-08-20T15:14:00+00:00"}]
    claims = {"x2": "wiki/log.md"}
    dupes, _ = nbd.find_dupes(group, claims)
    check("no status reported anywhere -> newest survives",
          dupes and dupes[0][1][0]["id"] == "x1")


TESTS = [test_interrupted_replace, test_basename_collision_never_deleted,
         test_same_owner_two_claims, test_newest_but_not_ready,
         test_none_ready_is_refused, test_missing_status_falls_back_to_newest]


def main():
    print("notebooklm-dedupe survivor-selection fence")
    for t in TESTS:
        print(f"\n{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print(f"PASSED: all checks in {len(TESTS)} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
