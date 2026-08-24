#!/usr/bin/env python3.11
"""
anti-pattern-candidates.py — Loop rec #5 gatherer (the DETERMINISTIC half of the
self-updating anti-patterns loop).

The self-updating loop is: gather candidate mistakes  ->  an INDEPENDENT model
inspector judges which are genuinely NEW anti-patterns (not already covered) and
drafts them in house style  ->  the result is staged for Matt's approval (NEVER
auto-appended to the curated page). This tool is only the first step: it
assembles the input bundle so the inspector has (a) the existing anti-patterns
to dedup against, and (b) the recent mistake corpus.

It NEVER edits wiki/synthesis/claude-anti-patterns.md. Read-only. The LLM
inspection + human approval happen around it.

Output: a markdown bundle to stdout.  Exit 0 (or 2 on read error).

Usage: anti-pattern-candidates.py [--log-entries N]   (default 12)
"""

import os
import re
import sys

VAULT = "/Users/matthewlavin/Claude code antigravity/obsidian "  # trailing space is intentional
AP   = os.path.join(VAULT, "wiki", "synthesis", "claude-anti-patterns.md")
LOG  = os.path.join(VAULT, "wiki", "log.md")

# Log ops whose entries typically encode a mistake-and-fix (the raw material for
# candidate anti-patterns). 'ingest'/'query' rarely do, so they're excluded.
#
# WIDENED 2026-08-07, and the omission had ALREADY BITTEN. The tuple used to be
# ("refactor", "schema", "lint"), which silently dropped every entry logged as
# 'correction', 'retraction', 'fix', 'build' or 'audit' — and 'correction' and
# 'retraction' are BY NAME nothing but mistakes. Measured on wiki/log.md that day:
# collected refactor 124 / schema 118 / lint 9; dropped correction 2 / retraction 2 /
# fix 4 / build 6 / audit 1. Four of the seven entries in that session's review
# corpus were uncollectable ops (3 build, 1 correction), and the 'correction' entry
# is where BOTH independent inspectors found their strongest material. Running the
# review off this tool's own output would have missed it.
#
# Second-order, and why a one-line constant matters: review_due() shares this tuple,
# so a session that logged its mistakes as 'correction' or 'fix' would never have
# tripped the review trigger at all. The gatherer for the anti-patterns loop had the
# exact blind spot the loop exists to catch.
MISTAKE_OPS = ("refactor", "schema", "lint",
               "fix", "correction", "retraction", "build", "audit", "test")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def existing_anti_patterns(text):
    """Return [(num, title, gist), ...] for every '### N. Title' entry, where
    gist is the first sentence of its 'What happens' block."""
    out = []
    lines = text.splitlines()
    heads = [(i, m) for i, ln in enumerate(lines)
             for m in [re.match(r"^###\s+(\d+)\.\s+(.*)$", ln)] if m]
    for idx, (i, m) in enumerate(heads):
        num, title = m.group(1), m.group(2).strip()
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        block = "\n".join(lines[i + 1:end])
        # Gist extraction, THREE tiers — because keying on one literal made this
        # silently return nothing for a third of the page.
        #
        # Measured on the live page 2026-08-07 (69 entries): 46 used
        # "**What happens**:", 7 used "**What happens.**" (period INSIDE the
        # bold), 1 used "**What happened (OpenFirehouse, 2026-07-14).**", and 15
        # had no what-happens opener at all. The old single-literal match
        # therefore produced an EMPTY gist for 23 of 69 — and they were the
        # NEWEST third (#29-33, #51-67), i.e. precisely the entries a fresh
        # proposal is most likely to duplicate. The dedup half of the rec #5 loop
        # had been running blind on the part of the corpus that needed it most,
        # and nothing reported it. (Anti-pattern #65's addendum: key on a
        # property the thing cannot avoid having.)
        #
        # Tier 3 is the load-bearing one — every entry has prose, so it cannot
        # rot when the opener style drifts again. It skips blockquote callouts,
        # list items, headings and table rows to find the first real sentence.
        gm = (re.search(r"\*\*What happen(?:s|ed)[^*]*\*\*[:.]?\s*(.+)", block)
              or re.search(r"(?m)^(?!\s*[->#|]|\s*$)(.+)$", block))
        gist = ""
        if gm:
            gist = re.split(r"(?<=[.!?])\s", gm.group(1).strip())[0]
            gist = re.sub(r"[*`]", "", gist)[:180]
        out.append((num, title, gist))
    return out


def recent_mistake_log(text, n):
    """Return the newest N log entries whose op is in MISTAKE_OPS.

    ORDER-AGNOSTIC BY DATE, deliberately (fixed 2026-08-19). This used to read
    from the TOP of the file assuming "log.md is newest-first" — an assumption
    codified during the 2026-08-05..07 sessions, which PREPENDED their entries.
    The documented convention (log.md's own header: "Append-only chronological
    record"; CLAUDE.md's grep-|-tail hint) and every session since 08-08 is
    newest at the BOTTOM — so the gather returned 08-07 entries as "newest"
    while 33 newer entries sat unread at the tail, and the 2026-08-19 rec #5
    review nearly ran on a 12-day-stale corpus. The fix keys on the entry's own
    date — a property it cannot avoid having (anti-pattern #65's addendum) —
    instead of its file position. Within one date, later file position wins:
    correct for the appended region, where every future entry lands."""
    parts = re.split(r"(?m)^(## \[\d{4}-\d{2}-\d{2}\][^\n]*)$", text)
    # parts = [pre, header1, body1, header2, body2, ...]
    entries = []
    for k in range(1, len(parts), 2):
        header = parts[k].strip()
        body = parts[k + 1] if k + 1 < len(parts) else ""
        om = re.match(r"## \[(\d{4}-\d{2}-\d{2})\]\s+(\w+)\s*\|", header)
        if not om:
            continue
        date, op = om.group(1), om.group(2)
        if op in MISTAKE_OPS:
            entries.append((date, k, header, body.strip()))
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
    return [(header, body) for _, _, header, body in entries[:n]]


def review_due():
    """Is an anti-pattern review DUE? Compares the newest mistake-bearing log
    entry date against the anti-patterns page's 'updated:' (last-reviewed) date.
    Returns (due, count_newer, reviewed_date, newest_mistake_date).

    Granularity is by DATE — a mistake logged on the SAME day as the last review
    won't register until the date rolls (fine for a gentle 'review due' nudge,
    not an alarm). This is the deterministic TRIGGER for the otherwise-manual
    rec #5 loop: it tells a session 'you've logged mistakes since the last
    anti-pattern review — run the inspector'."""
    ap = _read(AP)
    # PREFER a dedicated marker over the general-purpose `updated:` field.
    # `updated:` has two consumers: the page convention (bump it whenever you
    # edit the page) and this gate (bump it when you REVIEW). On 2026-08-24 a
    # session added ONE entry, bumped `updated:` per the page convention, and
    # silently cleared a standing "review due" warning that had 23 unreviewed
    # log entries behind it — a safety gate switched off by following an
    # unrelated convention correctly. One evaluator per fact
    # (claude-anti-patterns #46): `anti_patterns_reviewed:` means "the rec #5
    # ritual ran on this date" and nothing else. Falls back to `updated:` so
    # a page without the key behaves exactly as before.
    m = re.search(r"^anti_patterns_reviewed:\s*(\d{4}-\d{2}-\d{2})", ap, re.M) \
        or re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", ap, re.M)
    reviewed = m.group(1) if m else "0000-00-00"
    dates = re.findall(r"^## \[(\d{4}-\d{2}-\d{2})\]\s+(\w+)\s*\|", _read(LOG), re.M)
    mistake_dates = [d for d, op in dates if op in MISTAKE_OPS]
    newer = [d for d in mistake_dates if d > reviewed]
    newest = max(mistake_dates) if mistake_dates else "0000-00-00"
    return (len(newer) > 0, len(newer), reviewed, newest)


def main():
    if "--check-due" in sys.argv:
        try:
            due, count, reviewed, newest = review_due()
        except OSError as exc:
            sys.stderr.write(f"anti-pattern-candidates: {exc}\n")
            return 2
        if due:
            # Lead with a STABLE identity phrase ("anti-pattern review due") so the
            # nightly's non-escalation allowlist can match it — this is a
            # session-time nudge for the interactive agent, not a nightly alarm.
            print(f"anti-pattern review due: {count} mistake-bearing log entr"
                  f"{'y' if count == 1 else 'ies'} since the last review ({reviewed}); newest {newest}")
            return 1
        print(f"anti-pattern log in sync (last review {reviewed}; newest mistake-log entry {newest})")
        return 0

    n = 12
    if "--log-entries" in sys.argv:
        try:
            n = int(sys.argv[sys.argv.index("--log-entries") + 1])
        except (ValueError, IndexError):
            pass
    try:
        ap_text = _read(AP)
        log_text = _read(LOG)
    except OSError as exc:
        sys.stderr.write(f"anti-pattern-candidates: {exc}\n")
        return 2

    existing = existing_anti_patterns(ap_text)
    nums = [int(x[0]) for x in existing]
    used = sorted(set(nums))
    dupes = sorted({x for x in nums if nums.count(x) > 1})
    next_free = max(used) + 1 if used else 1
    gaps = [i for i in range(1, next_free) if i not in used]

    print("# Anti-pattern candidate bundle (for the independent inspector)")
    print()
    print("## Numbering state")
    print(f"- entries present: {len(existing)}  ·  highest number: {max(used) if used else 0}"
          f"  ·  next new integer: {next_free}")
    if dupes:
        print(f"- ⚠ DUPLICATE numbers in the file: {dupes} (do not reuse; the file has known dup headings)")
    if gaps:
        print(f"- gap numbers (unused): {gaps}")
    print()
    print("## Existing anti-patterns (dedup against these — a proposal must NOT restate one of these)")
    for num, title, gist in existing:
        print(f"- **#{num} {title}**" + (f" — {gist}" if gist else ""))
    print()
    print(f"## Recent mistake-bearing log entries (newest first, ops={'/'.join(MISTAKE_OPS)}, max {n})")
    print("_Fixes encode mistakes; a genuinely new + generalizable one may deserve an anti-pattern._")
    print()
    for header, body in recent_mistake_log(log_text, n):
        print(header)
        # first ~6 body lines, trimmed
        blines = [b for b in body.splitlines() if b.strip()][:6]
        for b in blines:
            print(b)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
