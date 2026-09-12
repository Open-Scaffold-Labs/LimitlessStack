#!/usr/bin/env python3.11
"""
Keeps the task files honest, so `/tasks` can actually be relied on.

WHY THIS FILE EXISTS. On 2026-08-24 Matt's personal task list held **385 unchecked
boxes**. An evidence audit found **186 were already shipped**. A second audit of the
93 "engineering" survivors — this time asking *"is this deliberate?"* as well as *"is
the code as described?"* — found **another 36** already shipped, ruled, parked, or
never tasks. Two of the rulings were written in the header comment of the very file
being audited. Matt, on being shown the list: *"so far it couldnt"* be relied on.

Three behaviours produced that, and each has a rule below:

  1. Sessions did not tick what they shipped.        -> AUDIT-DUE
  2. Sessions wrote their session WRITE-UP into the  -> NARRATIVE, CLOSED-SECTION
     task file. Active was 296 KB of which only
     110 KB was checkboxes; 63% was prose that
     already existed in wiki/log.md.
  3. Nothing ever re-read an old open item, so a     -> STALE, DUPLICATE
     box written in April was still "open" in
     August with nobody having looked.

This is DETECTION that runs every session, not a promise to remember. It cannot stop
a session writing prose into the wrong file; it can stop that going unnoticed for
four months. Wired into tools/limitless-preflight.sh, so every Roll Call sees it.

USAGE
    task-file-check.py            # check; exit 1 if findings
    task-file-check.py --quiet    # one line per finding, for the preflight
    task-file-check.py --prove    # self-test: each rule must fire on a planted fault
Exit 0 clean, 1 findings, 2 usage/internal error.
"""
import datetime
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
TASK_FILES = ["wiki/team-tasks.md"] + sorted(
    str(p.relative_to(VAULT)) for p in (VAULT / "wiki" / "my-tasks").glob("*.md")
    if "archive" not in p.name
)

AUDIT_DUE_DAYS = 14      # how long a task file may go without an evidence re-audit
ACTIVE_KB_CEILING = 200  # Active section size before it is a finding
PROSE_RATIO_MAX = 0.55   # share of Active that may be non-checkbox prose
STALE_DAYS = 45          # an open item under a section older than this was never re-read

OPEN_RE = re.compile(r'^\s*- \[ \] ')
BOX_RE = re.compile(r'^\s*- \[[ xX]\] ')
# A "section" is any `## ` topic banner or `### ` subsection inside Active,
# excluding the Active/Archive banners themselves. Widened from `^### ` on
# 2026-09-12, with the bounds fix: both live files head their TOPICS with
# `## ` and use `### ` only sometimes, so a `### `-only pattern could not
# reach 29% of team-tasks.md's open items and 43% of mlav1114.md's. Fixing
# the bounds alone would have left a checker that measured 71%/57% of the
# set and still reported clean — the shape of anti-pattern #68.
SEC_RE = re.compile(r'^#{2,3} (?!Active\b|Archive\b)(.*)$')
DATE_RE = re.compile(r'(\d{4}-\d{2}(?:-\d{2})?)')


def sec_date(title):
    """The date a section is aged against, or None when it carries none.

    Accepts `YYYY-MM` as well as `YYYY-MM-DD`, widened 2026-09-12. The strict
    form silently skipped `## 2026-06 — OpenFirehouse (open)` — a section three
    months old holding 3 open items — because a PARTIAL date read as NO date.
    Found by refusing to accept 92% STALE coverage as good enough.
    """
    m = DATE_RE.search(title)
    if not m:
        return None
    s = m.group(1)
    try:
        return datetime.date.fromisoformat(s if len(s) == 10 else s + "-01")
    except ValueError:
        return None


def split_active(lines):
    """Returns (start, end) of the Active region.

    Active is a BANNER over `## `-level topic sections, closed by the
    `## Archive` banner — NOT a container whose children are `### ` only.

    Until 2026-09-12 this ended the region at the next `## ` heading that was
    not `## Active`. Both live task files head their topics with `## `, so the
    very next heading terminated it and Active measured TWO LINES: the banner
    and a blank. Four of the five rules below ran over that empty set while
    `✓ task files are current` printed green over 340 open items, and
    `--prove` passed 6/6 the whole time because its fixtures were built in a
    shape neither real file has. See wiki/log.md [2026-09-12] `audit |
    audit-before-claim's references pointer RESOLVES from Cowork`.

    Both bounds now fail SAFE: no `## Active` starts the region after the
    frontmatter, no `## Archive` runs it to EOF. Over-scanning over-reports;
    the old shape scanned nothing and reported clean, which is the failure
    direction anti-pattern #38 names. Match `## Archive` by prefix only — an
    earlier attempt keyed on an Archive|CLOSED pattern and cut the region at a
    section TITLED "…is CLOSED…".
    """
    ia = None
    for i, l in enumerate(lines):
        if l.startswith("## Active"):
            ia = i
            break
    if ia is None:
        # No Active banner — e.g. my-tasks/draaen-osl.md, which heads its list
        # `## Open — pick up next session`. Start after the YAML frontmatter so
        # the body is measured rather than silently skipped.
        ia = 0
        if lines and lines[0].strip() == "---":
            for i, l in enumerate(lines[1:], start=1):
                if l.strip() == "---":
                    ia = i + 1
                    break
    for i in range(ia + 1, len(lines)):
        if lines[i].startswith("## Archive"):
            return ia, i
    return ia, len(lines)


def check_file(rel, today):
    p = VAULT / rel
    if not p.exists():
        return []
    text = p.read_text()
    lines = text.split("\n")
    out = []

    # ── AUDIT-DUE ────────────────────────────────────────────────────────────
    # Deliberately its own frontmatter key, NOT `updated:`. On 2026-08-24 the
    # anti-patterns review gate was found reading `updated:` — so a routine
    # page-edit date bump silenced a standing review with 23 entries behind it.
    # Same trap, same fix: one field, one meaning.
    m = re.search(r"^tasks_audited:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    if not m:
        out.append((rel, "AUDIT-DUE", "no `tasks_audited:` in frontmatter — this file has "
                                      "never had an evidence audit recorded"))
    else:
        age = (today - datetime.date.fromisoformat(m.group(1))).days
        if age > AUDIT_DUE_DAYS:
            out.append((rel, "AUDIT-DUE", f"last evidence audit {m.group(1)} ({age}d ago, "
                                          f"limit {AUDIT_DUE_DAYS}d) — open boxes are unverified"))

    ia, ir = split_active(lines)
    if ia is None:
        return out
    act = lines[ia:ir]
    kb = lambda xs: sum(len(x) + 1 for x in xs) / 1024

    # ── SCOPE ────────────────────────────────────────────────────────────────
    # Coverage floor, added 2026-09-12 with the bounds fix above. Every rule
    # below this line sees only `act`, so "the region captured nothing" and
    # "the file has nothing wrong" are indistinguishable from outside — which
    # is precisely how a 2-line Active region printed green over 340 open
    # items for months. The floor makes the vacuous case say so out loud.
    # Same discipline the canonical-sync loops and the label fence already
    # carry: a zero-item sweep and a zero-drift sweep must not look alike.
    file_open = sum(1 for l in lines if OPEN_RE.match(l))
    if file_open and not any(BOX_RE.match(l) for l in act):
        out.append((rel, "SCOPE", f"the Active scan captured 0 checkboxes while the file holds "
                                  f"{file_open} open item(s) — the section bounds are wrong, so "
                                  f"every Active-scoped rule here is vacuous"))

    # ── NARRATIVE ────────────────────────────────────────────────────────────
    prose = [l for l in act if l.strip() and not BOX_RE.match(l)]
    if kb(act) > ACTIVE_KB_CEILING:
        out.append((rel, "NARRATIVE", f"Active is {kb(act):.0f} KB (ceiling {ACTIVE_KB_CEILING}) "
                                      f"— session write-ups belong in wiki/log.md, not here"))
    elif kb(act) > 20 and kb(prose) / max(kb(act), 0.001) > PROSE_RATIO_MAX:
        out.append((rel, "NARRATIVE", f"{100*kb(prose)/kb(act):.0f}% of Active is non-checkbox "
                                      f"prose ({kb(prose):.0f} of {kb(act):.0f} KB)"))

    # ── CLOSED-SECTION ───────────────────────────────────────────────────────
    # The convention these files already declare: a section with nothing open
    # belongs under Archive. Enforcing it is what keeps Active readable.
    secs = [(i, m.group(1)) for i, l in enumerate(act) if (m := SEC_RE.match(l))]
    closed = []
    for n, (i, title) in enumerate(secs):
        end = secs[n + 1][0] if n + 1 < len(secs) else len(act)
        body = act[i:end]
        if any(BOX_RE.match(x) for x in body) and not any(OPEN_RE.match(x) for x in body):
            closed.append(title[:60])
    if closed:
        out.append((rel, "CLOSED-SECTION", f"{len(closed)} Active section(s) have zero open items "
                                           f"— move to Archive (first: {closed[0]})"))

    # ── STALE ────────────────────────────────────────────────────────────────
    # Fires on EITHER half, because an item nothing could age is not an item
    # that passed. Before 2026-09-12 an open item under an undated section was
    # skipped in silence — 29 of them across the two live files, 20 of those in
    # "Yours to decide" / "FOR MATT" buckets. Same reason SCOPE exists above:
    # "found nothing" and "measured nothing" must never look alike, and the
    # coverage question does not stop being real one level down.
    stale = unaged = 0
    cur_date = None
    for l in act:
        if (sm := SEC_RE.match(l)):
            cur_date = sec_date(sm.group(1))
        elif OPEN_RE.match(l):
            if cur_date is None:
                unaged += 1
            elif (today - cur_date).days > STALE_DAYS:
                stale += 1
    if stale or unaged:
        bits = []
        if stale:
            # ⚠ The wording is load-bearing and was sharpened 2026-09-12 (Matt:
            # "just because a task is pending a long time doesn't mean it's
            # necessarily done"). AGE IS NOT EVIDENCE OF COMPLETION. A long-open
            # item is equally likely to be real work nobody has looked at, and
            # the remediation line this finding prints beside ("tick what you
            # shipped, archive closed sections") biases toward closing. The
            # finding must therefore carry its own guard: this rule asks you to
            # LOOK, it never licenses a tick.
            bits.append(f"{stale} open item(s) under sections older than {STALE_DAYS}d — nobody "
                        f"has re-read them. AGE IS NOT EVIDENCE THEY ARE DONE: re-verify each "
                        f"against the code and search for a ruling before ticking or archiving; "
                        f"a long-ignored item that is still genuinely owed is the expected case")
        if unaged:
            bits.append(f"{unaged} open item(s) under a section carrying NO date, so they cannot "
                        f"be aged at all — date the section or move the items")
        out.append((rel, "STALE", "; ".join(bits)))

    # ── DUPLICATE ────────────────────────────────────────────────────────────
    seen = {}
    for l in act:
        # ♻️ marks a duplicate the author has SEEN and chose to keep (the two
        # copies live under different sections and both are meaningful). Same
        # contract as `# unbound-ok:` in shell-unbound-check.py: a marker states
        # a reason, it does not silence a finding you have not looked at.
        if "♻️" in l:
            continue
        if OPEN_RE.match(l):
            k = re.sub(r'\s+', ' ', OPEN_RE.sub('', l).split("  ")[0]).strip()[:90]
            if len(k) > 25:
                seen[k] = seen.get(k, 0) + 1
    dups = {k: v for k, v in seen.items() if v > 1}
    if dups:
        out.append((rel, "DUPLICATE", f"{len(dups)} open item(s) appear more than once "
                                      f"— one of them will never be ticked"))
    return out


def run(today=None):
    today = today or datetime.date.today()
    findings = []
    for rel in TASK_FILES:
        findings += check_file(rel, today)
    return findings


def prove():
    """Each rule must FIRE on a planted fault. A checker nobody has seen fail is a
    checker nobody should trust — and 'no findings' and 'scanned nothing' look
    identical from outside."""
    import tempfile
    today = datetime.date.today()
    old = (today - datetime.timedelta(days=120)).isoformat()
    cases = {
        "AUDIT-DUE": f"---\ntype: tasks\n---\n\n## Active\n\n### {today} x\n\n- [ ] a thing to do here\n",
        "NARRATIVE": ("---\ntasks_audited: %s\n---\n\n## Active\n\n### %s x\n\n- [ ] one box\n\n"
                      % (today, today)) + ("filler prose line that is not a checkbox\n" * 900),
        "CLOSED-SECTION": f"---\ntasks_audited: {today}\n---\n\n## Active\n\n### {today} done\n\n- [x] shipped\n\n### {today} live\n\n- [ ] open\n",
        "STALE": f"---\ntasks_audited: {today}\n---\n\n## Active\n\n### {old} ancient\n\n- [ ] never re-read since then\n",
        "DUPLICATE": f"---\ntasks_audited: {today}\n---\n\n## Active\n\n### {today} x\n\n- [ ] the very same wording repeated here\n- [ ] the very same wording repeated here\n",
        # Active legitimately empty while open items sit below the Archive
        # banner: every rule below SCOPE is vacuous and must say so.
        "SCOPE": f"---\ntasks_audited: {today}\n---\n\n## Active\n\n## Archive — shipped\n\n- [ ] an open item parked below the Archive banner\n",
    }
    ok = True
    print("\nproving each rule fires on a planted fault\n")
    for rule, content in cases.items():
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.md"
            f.write_text(content)
            global VAULT
            keep, VAULT = VAULT, Path(d)
            got = {r for _, r, _ in check_file("t.md", today)}
            VAULT = keep
        hit = rule in got
        ok &= hit
        print(f"  {'✓' if hit else '✗'} {rule:16s} fired={hit}   (also saw: {sorted(got - {rule}) or 'nothing'})")

    # ── BOUNDS regression (added 2026-09-12) ─────────────────────────────────
    # Built in the REAL files' shape, which is the whole point: `## Active` is
    # a BANNER over dated `## ` topic sections that carry items directly,
    # closed by `## Archive`. Every other fixture above is authored in a shape
    # the live files do NOT have — which is exactly how 6/6 green coexisted
    # with a checker measuring an empty set.
    #
    # This one assertion fences BOTH of the day's fixes, and fails if either
    # regresses: restore the old bounds and Active collapses to 2 lines;
    # restore `SEC_RE = ^### ` and the `## ` banner stops being a section, so
    # its date never loads and the item is never aged. Either way STALE goes
    # silent and this goes red.
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.md"
        f.write_text(f"---\ntasks_audited: {today}\n---\n\n## Active\n\n"
                     f"## Topic {old} — a `## ` banner carrying items directly\n\n"
                     f"- [ ] an open item neither the old bounds nor `^### ` could reach\n\n"
                     f"## Archive — shipped\n")
        keep, VAULT = VAULT, Path(d)
        msgs = {r: m for _, r, m in check_file("t.md", today)}
        VAULT = keep
    # Assert on the AGED half specifically, not merely that STALE fired. When
    # STALE gained its unaged half on 2026-09-12 a bare `"STALE" in got` stopped
    # distinguishing "aged it correctly" from "could not age it at all", and
    # reverting SEC_RE quietly stopped turning this red. A fence that survives
    # the mutation it exists to catch is #71.
    hit = "older than" in msgs.get("STALE", "") and "SCOPE" not in msgs
    ok &= hit
    print(f"  {'✓' if hit else '✗'} BOUNDS           Active spans `## ` topic sections, item AGED "
          f"(SCOPE quiet={'SCOPE' not in msgs})")

    # ── DATE-GRAIN + UNAGED regressions (added 2026-09-12) ───────────────────
    # Two halves of one lesson, both found by refusing to accept a 92% coverage
    # figure: a PARTIAL date is not NO date, and an item nothing can age must be
    # REPORTED rather than skipped. Assert on the message text, not just the
    # rule name — STALE now has two halves and either can go silent alone.
    for label, body, want in (
        ("PARTIAL-DATE",
         f"## {old[:7]} — a section dated YYYY-MM, as team-tasks.md writes some\n\n"
         f"- [ ] an open item that a YYYY-MM-DD-only pattern read as undated\n",
         "older than"),
        ("UNAGED",
         "### a section heading carrying no date anywhere in it\n\n"
         "- [ ] an open item that nothing can age\n",
         "cannot be aged"),
        # Fences the GUARD, not just the count. STALE prints beside a
        # remediation line that says "tick what you shipped, archive closed
        # sections" — closure-biased — so the finding has to carry its own
        # "age is not evidence" warning or a hurried session reads the pair as
        # permission to tick. If someone rewords that guard away, this goes red
        # and they have to do it on purpose.
        ("NOT-EVIDENCE",
         f"## {old} — an old section holding work that is still genuinely owed\n\n"
         f"- [ ] real work nobody has looked at in months — NOT done\n",
         "AGE IS NOT EVIDENCE"),
    ):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.md"
            f.write_text(f"---\ntasks_audited: {today}\n---\n\n## Active\n\n"
                         + body + "\n## Archive — shipped\n")
            keep, VAULT = VAULT, Path(d)
            msgs = {r: m for _, r, m in check_file("t.md", today)}
            VAULT = keep
        hit = want in msgs.get("STALE", "")
        ok &= hit
        print(f"  {'✓' if hit else '✗'} {label:16s} STALE reports it "
              f"(wanted {want!r}, got {msgs.get('STALE', 'NO STALE FINDING')[:52]!r})")

    # negative control: a healthy file must produce NOTHING
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.md"
        f.write_text(f"---\ntasks_audited: {today}\n---\n\n## Active\n\n### {today} today\n\n- [ ] a genuinely open item\n\n## Archive\n")
        keep, VAULT = VAULT, Path(d)
        clean = check_file("t.md", today)
        VAULT = keep
    ok &= not clean
    print(f"  {'✓' if not clean else '✗'} NEGATIVE CONTROL a healthy file produces no findings "
          f"({len(clean)} found)")
    print()
    return 0 if ok else 1


def main():
    if "--prove" in sys.argv:
        return prove()
    quiet = "--quiet" in sys.argv
    findings = run()
    if not quiet:
        print(f"\ntask-file check — {len(TASK_FILES)} file(s)\n")
    if not findings:
        if not quiet:
            print("  ✓ task files are current\n")
        return 0
    for rel, rule, msg in findings:
        print(f"  ✗ [{rule}] {rel} — {msg}")
    if not quiet:
        print(f"\n  {len(findings)} finding(s)\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
