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
SEC_RE = re.compile(r'^### (.*)$')
DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')


def split_active(lines):
    """Returns (start, end) of the Active section, or (None, None)."""
    ia = ir = None
    for i, l in enumerate(lines):
        if ia is None and l.startswith("## Active"):
            ia = i
        elif ia is not None and l.startswith("## ") and not l.startswith("## Active"):
            ir = i
            break
    return ia, (ir if ir is not None else len(lines))


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
    stale = 0
    cur_date = None
    for l in act:
        if (sm := SEC_RE.match(l)):
            d = DATE_RE.search(sm.group(1))
            cur_date = datetime.date.fromisoformat(d.group(1)) if d else None
        elif OPEN_RE.match(l) and cur_date and (today - cur_date).days > STALE_DAYS:
            stale += 1
    if stale:
        out.append((rel, "STALE", f"{stale} open item(s) under sections older than {STALE_DAYS}d "
                                  f"— never re-verified against the code"))

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
