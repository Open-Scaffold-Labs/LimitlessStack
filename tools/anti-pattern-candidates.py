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
MISTAKE_OPS = ("refactor", "schema", "lint")


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
        gm = re.search(r"\*\*What happens\*\*:\s*(.+)", block)
        gist = ""
        if gm:
            gist = re.split(r"(?<=[.!?])\s", gm.group(1).strip())[0]
            gist = re.sub(r"[*`]", "", gist)[:180]
        out.append((num, title, gist))
    return out


def recent_mistake_log(text, n):
    """Return the newest N log entries whose op is in MISTAKE_OPS. log.md is
    newest-first, entries start with '## [YYYY-MM-DD] <op> | <label>'."""
    parts = re.split(r"(?m)^(## \[\d{4}-\d{2}-\d{2}\][^\n]*)$", text)
    # parts = [pre, header1, body1, header2, body2, ...]
    entries = []
    for k in range(1, len(parts), 2):
        header = parts[k].strip()
        body = parts[k + 1] if k + 1 < len(parts) else ""
        om = re.match(r"## \[\d{4}-\d{2}-\d{2}\]\s+(\w+)\s*\|", header)
        op = om.group(1) if om else ""
        if op in MISTAKE_OPS:
            entries.append((header, body.strip()))
        if len(entries) >= n:
            break
    return entries


def main():
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
