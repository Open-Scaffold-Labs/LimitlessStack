#!/usr/bin/env python3.11
"""
anti-pattern-index.py — generate + validate the retrieval index at the top of
wiki/synthesis/claude-anti-patterns.md.

WHY THIS IS A SCRIPT AND NOT A HAND-WRITTEN TABLE
-------------------------------------------------
A three-agent audit (2026-08-07) found the page had no index at all: 69 entries
under one flat heading, and TITLES were the only retrieval surface. Judged as an
index they fail — for "I am about to report something DONE" only 1 of the 11
governing entries is findable by title.

The obvious fix is to hand-write an index. That would be **anti-pattern #46
committed inside the anti-patterns page**: two places computing one derived fact
(what entries exist) drift silently, and nothing errors when they do. So the
block in the page is GENERATED from the headings, the curated judgment lives
here in exactly one place, and `--check` fails when the two disagree.

WHAT IS CURATED vs WHAT IS DERIVED
----------------------------------
DERIVED (never hand-edit): the entry numbers, titles, and the rendered block.
CURATED (edit here, below):  TRIPWIRES and SITUATIONS — which entries a phrase or
                             a moment should route to. That is judgment; it
                             cannot be derived. But it IS validated:
  * every number cited here must exist as a heading  -> else --check fails
  * every heading must be cited by at least one row  -> else --check fails

That second rule is the load-bearing one. Add a #70 and the preflight goes yellow
until it is indexed, so the index cannot silently fall behind the page.

USAGE
  anti-pattern-index.py            # rewrite the block in the page
  anti-pattern-index.py --check    # exit 1 if stale / mis-cited / uncovered
  anti-pattern-index.py --print    # emit the block to stdout, touch nothing
"""

import os
import re
import sys

VAULT = "/Users/matthewlavin/Claude code antigravity/obsidian "  # trailing space intentional
PAGE = os.path.join(VAULT, "wiki", "synthesis", "claude-anti-patterns.md")

BEGIN = "<!-- BEGIN GENERATED INDEX — edit tools/anti-pattern-index.py, never this block -->"
END = "<!-- END GENERATED INDEX -->"

# Numbers that exist as headings but are deliberately not indexed.
EXEMPT = {"9"}  # reserved slot, holds no lesson

# Numbers used twice on the page. A citation of the bare number is ambiguous;
# the index always shows the letter so a reader knows which one is meant.
DUP_LABELS = {
    ("13", 0): "13a", ("13", 1): "13b",
    ("23", 0): "23a", ("23", 1): "23b",
}

# ---------------------------------------------------------------- CURATED ----
# §0 — phrases and moments that must stop you mid-sentence.
TRIPWIRES = [
    ('"for now" · "a future upgrade" · "MVP then iterate" · "harden it later" · "the normal arc" · "standard practice"',
     ["23a", "26"],
     "The framing IS the bug. Name the shortcut as a shortcut and build the higher bar."),
    ('"the one genuine gap" · "nobody ships this — that\'s the opportunity"',
     ["31", "51"],
     "Absence marks a product BOUNDARY more often than an opening. Name the comparison set first."),
    ('"I can\'t verify that from here" · "you\'ll need to do this part"',
     ["41", "53"],
     "A stated limit is a claim at the same evidence bar as a stated fact. Enumerate your tools and try the cheapest."),
    ('"flagged for Matt" · "left for a future session" · "not attempted here"',
     ["45", "50"],
     "A live hole in a safety mechanism is work, not a finding. If you can write the fix in a sentence, do it now."),
    ('"worth Dale\'s review" · "this needs sign-off"',
     ["55"],
     "Name the trigger (DEFINER, RLS-bypass, public surface, legal FK) or do the work."),
    ('"it\'s not in the codebase" · "no results" · "not present"',
     ["42", "25", "54"],
     "Run a positive control in the SAME command. A command that never ran looks exactly like a clean search."),
    ('"build passed" · "tests pass" · "deploy succeeded" · "returned 200/201"',
     ["23b", "29", "30", "33", "38", "64"],
     "None of those measures the effect. Ask: could this check have come out the other way?"),
    ('"the migration is pending"',
     ["33"],
     "That state does not exist. It is an outage with a to-do list. Both halves ship or neither does."),
    ('"the monitor says it\'s healthy" — or you are BUILDING a monitor',
     ["67", "38", "65"],
     "Write the mechanism's own failure story as a test. Its instance of F is the one nothing is watching."),
    ('"let me just restart / kill / reinstall / reset that" (on Matt\'s machine)',
     ["58", "32"],
     "A blocker is the highest-information moment in the session. Read it; never route around it by mutating his environment."),
    ('putting quote marks around a spec, contract or source phrase',
     ["56"],
     'Quote marks mean you re-read the source THIS session and copied it. Otherwise write "paraphrasing §X".'),
    ('a test total, a node count or a coverage number that DROPPED',
     ["29", "65"],
     "A shrinking total is a finding. Reconcile the arithmetic: previous + new = current, exactly."),
    ('a probe you have now run THREE times that keeps returning the same thing',
     ["29", "40", "25"],
     "An unchanging reading is a claim about the INSTRUMENT until proven otherwise. Stop polling; check the probe (`ps -o etime=`, log mtime). Never poll liveness by `pgrep -f <name>` — it matches your own poll."),
]

# §1 — SITUATION -> entries. Every non-exempt heading must appear at least once.
SITUATIONS = [
    ("report something DONE / write a wrap-up",
     ["12", "29", "30", "38", "45", "50", "56", "57", "62", "64", "67"]),
    ("say a tool, resource or capability is unavailable",
     ["41", "53", "27", "24", "17", "5"]),
    ("push code that needs a schema change, env var, flag or migration",
     ["33", "54", "29", "44", "39"]),
    ("build a monitor, detector, gate or coverage check",
     ["67", "38", "61", "65", "35", "36", "13b"]),
    ("replace a fragile mechanism with a \"more robust\" one",
     ["34", "67", "38", "46"]),
    ("verify a UI or visual change",
     ["64", "65", "66", "30", "15"]),
    ("diagnose a production failure",
     ["17", "25", "40", "48", "42", "15"]),
    ("edit or \"fix\" existing code",
     ["28", "60", "46", "58", "20"]),
    ("run a market or competitive pass",
     ["47", "51", "31"]),
    ("write a spec, phase plan or gameplan",
     ["47", "63", "31", "26"]),
    ("ask Matt a question",
     ["21", "55", "53", "32", "57"]),
    ("take a destructive or irreversible action",
     ["32", "58", "43"]),
    ("restore or import data into a live system",
     ["43", "32"]),
    ("trust a document, wiki page, CLAUDE.md or handoff",
     ["18", "52", "62", "63", "13b"]),
    ("work in a git checkout / commit / push",
     ["62", "22", "7", "14"]),
    ("look up a per-record fact (a UN, a CAS, a price, a CVE)",
     ["16"]),
    ("reason about authorization or a write path on a table",
     ["44", "61", "46"]),
    ("run a slow verifier, or go quiet for more than a few minutes",
     ["49", "13a"]),
    ("start a session, or answer from active context",
     ["1", "21", "6", "8", "19", "10", "63"]),
    ("write to or refresh a NotebookLM source",
     ["12", "19", "10", "6"]),
    ("integrate an external API or SDK",
     ["2", "8"]),
    ("choose infrastructure, a vendor or a platform",
     ["3", "20"]),
    ("debug something that resists a fix",
     ["4", "17", "40", "49"]),
    ("write a loop, a scheduled job or anything with run-to-run state",
     ["35", "36", "37", "67"]),
    ("write down a rule or lesson mid-session",
     ["59", "26", "50"]),
    ("deploy or merge to production",
     ["11", "22", "33", "43"]),
]
# ------------------------------------------------------------ /CURATED ------


def read_page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def headings(text):
    """[(number_str, label, title)] in page order; label disambiguates dups."""
    raw = re.findall(r"(?m)^###\s+(\d+)\.\s+(.*)$", text)
    seen = {}
    out = []
    for num, title in raw:
        idx = seen.get(num, 0)
        seen[num] = idx + 1
        out.append((num, DUP_LABELS.get((num, idx), num), title.strip()))
    return out


def labels_for(num, heads):
    """Resolve a curated citation to display label(s).

    A citation may be a bare number ('13') or an explicit label ('23a'). The
    explicit form matters: the two #23s teach OPPOSITE-domain lessons, so a
    tripwire about deferral means 23a only and one about a green build means 23b
    only. Expanding a bare '23' to both would send every reader to the wrong
    half half the time — which is the collision defect, re-created in the index
    built to route around it.
    """
    hits = [lab for n, lab, _ in heads if n == num]
    if hits:
        return hits
    if any(lab == num for _, lab, _ in heads):   # already an explicit label
        return [num]
    return [num]                                  # unknown; validate() reports it


def render(heads):
    known = {n for n, _, _ in heads}
    lines = [BEGIN, ""]
    lines.append(f"**{len(heads)} entries.** Numbers are permanent IDs — they are cited **213 times "
                 "across 67 files**, 79 of them in the append-only `wiki/log.md`. "
                 "**Never renumber.** `#9` is reserved; `#13` and `#23` each appear twice "
                 "(13a/13b, 23a/23b — see the callouts on those entries).")
    lines.append("")
    lines.append("Read §0 and §1. That is the reminder layer, and it takes two minutes. "
                 "The entries themselves are the rulebook — reach for one when its situation is yours.")
    lines.append("")
    lines.append("### §0 — TRIPWIRES. If you are about to write or think one of these, STOP.")
    lines.append("")
    lines.append("| You are about to say… | Read | Because |")
    lines.append("|---|---|---|")
    for phrase, nums, why in TRIPWIRES:
        refs = ", ".join(f"**#{lab}**" for n in nums for lab in labels_for(n, heads))
        lines.append(f"| {phrase} | {refs} | {why} |")
    lines.append("")
    lines.append("### §1 — SITUATION INDEX. Find your moment, then read those entries.")
    lines.append("")
    lines.append("| I am about to… | Entries |")
    lines.append("|---|---|")
    for sit, nums in SITUATIONS:
        refs = " · ".join(f"#{lab}" for n in nums for lab in labels_for(n, heads))
        lines.append(f"| …{sit} | {refs} |")
    lines.append("")
    lines.append(f"<sub>Generated by `tools/anti-pattern-index.py` from the `### N.` headings. "
                 f"Do not hand-edit this block — a hand-kept index is a second evaluator of "
                 f"\"what entries exist\", which is anti-pattern #46 inside the anti-patterns "
                 f"page. Coverage is enforced: every entry must appear in §1 or the preflight "
                 f"goes yellow.</sub>")
    lines.append("")
    lines.append(END)
    assert known  # silence linters; `known` documents intent
    return "\n".join(lines)


def validate(heads):
    """Returns a list of problem strings (empty == clean)."""
    problems = []
    # Coverage is measured over LABELS (13a, 13b, 23a, 23b), not bare numbers —
    # otherwise indexing 23a alone would mark 23b covered, and the collision the
    # index exists to disambiguate would hide inside the index.
    known = {lab for _, lab, _ in heads}
    bare = {n for n, _, _ in heads}
    cited = set()
    for _, nums, _ in TRIPWIRES:
        cited.update(nums)
    for _, nums in SITUATIONS:
        cited.update(nums)
    expanded = set()
    for c in cited:
        expanded.update(labels_for(c, heads) if c in bare else [c])
    ghosts = sorted(expanded - known, key=lambda s: (int(re.sub(r"\D", "", s)), s))
    if ghosts:
        problems.append("index cites entries that do not exist: "
                        + ", ".join("#" + g for g in ghosts))
    uncovered = sorted((known - expanded) - EXEMPT,
                       key=lambda s: (int(re.sub(r"\D", "", s)), s))
    if uncovered:
        problems.append("entries missing from the §1 situation index: "
                        + ", ".join("#" + u for u in uncovered)
                        + "  →  add them to SITUATIONS in tools/anti-pattern-index.py")
    return problems


def splice(text, block):
    if BEGIN in text and END in text:
        pre = text.split(BEGIN)[0]
        post = text.split(END, 1)[1]
        return pre + block + post
    # First install: insert directly after the H1 intro, before the entries.
    anchor = "\n## Rules I keep drifting from\n"
    if anchor not in text:
        raise SystemExit("anti-pattern-index: cannot find the '## Rules I keep drifting from' anchor")
    return text.replace(anchor, "\n" + block + "\n" + anchor, 1)


def main():
    text = read_page()
    heads = headings(text)
    if not heads:
        sys.stderr.write("anti-pattern-index: no '### N. Title' headings found — "
                         "has the heading format changed?\n")
        return 2

    problems = validate(heads)
    block = render(heads)

    if "--print" in sys.argv:
        print(block)
        return 1 if problems else 0

    if "--check" in sys.argv:
        for p in problems:
            print(p)
        current = ""
        if BEGIN in text and END in text:
            current = BEGIN + text.split(BEGIN, 1)[1].split(END, 1)[0] + END
        else:
            print("index block not present in the page — run tools/anti-pattern-index.py")
            return 1
        if current.strip() != block.strip():
            print("index block is STALE vs the headings — run tools/anti-pattern-index.py")
            return 1
        if problems:
            return 1
        print(f"anti-pattern index in sync ({len(heads)} entries, all indexed)")
        return 0

    for p in problems:
        sys.stderr.write("WARN: " + p + "\n")
    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write(splice(text, block))
    print(f"index written ({len(heads)} entries, {len(TRIPWIRES)} tripwires, "
          f"{len(SITUATIONS)} situations)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
