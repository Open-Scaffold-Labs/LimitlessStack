#!/usr/bin/env python3.11
"""
Static guard against the `set -u` unbound-variable class in this repo's shell tools.

WHY THIS FILE EXISTS. Twice, three months apart, tools/limitless-preflight.sh
shipped a reference to a variable that was unset at that point in the run:

  dd10778 (2026-05-18)  ${WARNINGS[*]} — an ARRAY that is empty on a clean run.
                        Died inside $( ), so the parent exited 0 and it was
                        filed as "cosmetic". Class left open.
  08a2275 (2026-08-23)  $LIMITLESS_STACK_HOME — a SCALAR used 172 lines above
                        its default. Died at top level, killing checks 4-7.

Both were caught by a human noticing, after shipping. The completion assertion
added 2026-08-24 makes the second shape die LOUDLY — but loud death is
detection, not prevention. This file is the prevention half: the bug should not
be committable in the first place.

  Rule A — a scalar referenced BEFORE its first assignment, unguarded.
  Rule B — an array expanded as ${A[@]} / ${A[*]} without a :- or + guard.

RULE B NEEDS A WORD, because the obvious fix is wrong. On bash 3.2 (which is
what /bin/bash is on this Mac, and what the shebang selects) even a DECLARED,
EMPTY array explodes:

    $ bash -c 'set -u; A=(); echo "${A[@]}"'
    bash: A[@]: unbound variable

...so `A=()` at the top does NOT make it safe. And you cannot blanket-add `:-`,
because on an empty array `"${A[@]:-}"` expands to ONE EMPTY STRING rather than
zero words — `for x in "${A[@]:-}"` runs once instead of never. Measured, both.

So Rule B does not demand a mechanical fix. It demands that every unguarded
array expansion be either genuinely guarded or EXPLICITLY CLAIMED SAFE on its
own line:

    for w in "${WARNINGS[@]}"; do   # unbound-ok: reached only when YELLOW > 0

An unmarked one fails the check. That makes the May-2026 shape impossible to
add silently while leaving the existing, control-flow-safe sites alone.

USAGE
    shell-unbound-check.py [FILE ...]   # default: every tools/*.sh in the vault
    shell-unbound-check.py --prove      # run against the two REAL historical
                                        # bugs pulled from git: both must FAIL,
                                        # the current file must PASS.
Exit 0 = clean, 1 = findings, 2 = usage/internal error.
"""
import re
import subprocess
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent

# Names bash/the OS provides. Referencing these before assignment is fine.
SHELL_PROVIDED = {
    "HOME", "PATH", "PWD", "OLDPWD", "USER", "LOGNAME", "SHELL", "SHLVL", "TERM",
    "IFS", "LINENO", "RANDOM", "SECONDS", "PPID", "UID", "EUID", "HOSTNAME",
    "HOSTTYPE", "OSTYPE", "MACHTYPE", "TMPDIR", "LANG", "LC_ALL", "EDITOR",
    "BASH", "BASH_SOURCE", "BASH_VERSION", "BASH_COMMAND", "BASH_REMATCH",
    "BASH_SUBSHELL", "FUNCNAME", "PIPESTATUS", "REPLY", "SECONDS", "COLUMNS",
    "LINES", "PS1", "PS2", "PS4", "GLOBIGNORE", "CDPATH", "SSH_AUTH_SOCK",
}

# A reference is GUARDED when it supplies its own fallback: ${V:-x} ${V-x}
# ${V:+x} ${V+x} ${V:?x} ${V:=x} ${#V} ${V:offset}. Only braced forms can.
GUARD_CHARS = set(":-+?=")

# Every way this codebase creates a name. Missing one of these produces a FALSE
# POSITIVE, which is how a checker gets switched off — so they are enumerated
# rather than approximated. (My first draft modelled only `VAR=` and reported 32
# findings of which 31 were bogus, while MISSING the one real bug.)
# NOTE the quote characters in the class: `trap '_rc=$?` assigns _rc immediately
# after a single quote. Leaving them out cost a false positive on the very trap
# this checker's sibling fence protects.
SEPARATORS = r"(?:^|[;&|(){}'\"!]|\bthen\b|\belse\b|\belif\b|\bif\b|\bdo\b|\bexport\b|\blocal\b|\bdeclare\b|\btypeset\b|\breadonly\b|&&|\|\|)\s*!?"
RE_ASSIGN = re.compile(SEPARATORS + r"\s*([A-Za-z_]\w*)(?:\+?=|\[[^]]*\]=)")
RE_DECL_LINE = re.compile(r"\b(?:local|declare|typeset|readonly|export)\s+(.*)")
RE_DECL_NAME = re.compile(r"\b([A-Za-z_]\w*)=")
RE_DECL_BARE = re.compile(r"\b([A-Za-z_]\w*)\b")
RE_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\b")
RE_READ = re.compile(r"\bread\s+((?:-\w+\s+|-d\s*\S+\s+)*)((?:[A-Za-z_]\w*\s*)+)")
RE_FUNCARG = re.compile(r"\bgetopts\s+\S+\s+([A-Za-z_]\w*)")
RE_REF = re.compile(r"\$(\{)?([A-Za-z_]\w*)(\[[@*]\])?(.?)")
RE_ARRAY_REF = re.compile(r"\$\{([A-Za-z_]\w*)\[([@*])\]([^}]*)\}")
MARKER = "unbound-ok:"


RE_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")


def strip_comment(line: str, quote=None):
    """Remove a trailing comment AND blank out single-quoted spans, respecting
    quotes. Cheap state machine — good enough for shell, and it must not eat a
    `#` inside a string.

    WHY single-quoted text is blanked: inside '…' the shell does not expand, so
    `sed '1d;$d'` and `awk '{print $2}'` are not variable references — they are
    another language's syntax. Scanning them produced a false positive on
    install.sh ($d, sed's last-line address) and would produce one on every awk
    program in this repo. A checker that cries wolf gets switched off.

    KNOWN LIMIT, stated rather than hidden: a variable referenced inside a
    single-quoted `trap '…' EXIT` body IS expanded later, at trap time, and
    this pass cannot see it. That region is covered by the two RUNTIME layers
    instead — test-preflight-abort.sh's stderr assertion and the nightly's
    shell-diagnostic escalation. Blanking is applied to assignments too, so the
    model stays self-consistent: single-quoted text neither defines nor uses.
    """
    out, i = [], 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                out.append(c)
                i += 1
                if i < len(line):
                    out.append(line[i])
                i += 1
                continue
            if c == quote:
                quote = None
                out.append(c)
            else:
                # blank single-quoted content; keep double-quoted (it expands)
                out.append(" " if quote == "'" else c)
        else:
            if c in "'\"":
                quote = c
                out.append(c)
            elif c == "#" and (i == 0 or line[i - 1] in " \t;&|("):
                break
            else:
                out.append(c)
        i += 1
    return "".join(out), quote


def scan(path: Path):
    """Returns a list of (line_no, rule, name, text) findings."""
    lines = path.read_text(errors="replace").split("\n")
    assigned: dict[str, int] = {}
    used: dict[str, tuple[int, str]] = {}
    array_findings = []

    quote = None          # carried ACROSS lines: `trap '…` spans many of them
    heredoc = None        # terminator we are skipping to, if inside a heredoc

    for n, raw in enumerate(lines, 1):
        # Heredoc bodies are data (or another language), never shell code.
        # Without this, one apostrophe in a python heredoc — "don't" — opens a
        # quote that blanks the rest of the file, and the checker silently sees
        # nothing. A checker that fails quiet is worse than none.
        if heredoc is not None:
            if raw.strip() == heredoc:
                heredoc = None
            continue
        if quote is None:
            m = RE_HEREDOC.search(raw)
            if m:
                heredoc = m.group(2)
        if quote is None and raw.lstrip().startswith("#"):
            continue
        code, quote = strip_comment(raw, quote)
        if not code.strip():
            continue

        # ---- names created on this line -------------------------------
        for m in RE_ASSIGN.finditer(code):
            assigned.setdefault(m.group(1), n)
        d = RE_DECL_LINE.search(code)
        if d:
            body = d.group(1)
            names = RE_DECL_NAME.findall(body)
            if not names:                       # `local a b c` — bare names
                names = [x for x in RE_DECL_BARE.findall(body) if not x.startswith("-")]
            for name in names:
                assigned.setdefault(name, n)
        for m in RE_FOR.finditer(code):
            assigned.setdefault(m.group(1), n)
        for m in RE_READ.finditer(code):
            for name in m.group(2).split():
                assigned.setdefault(name, n)
        for m in RE_FUNCARG.finditer(code):
            assigned.setdefault(m.group(1), n)

        # ---- Rule B: array expansions ---------------------------------
        for m in RE_ARRAY_REF.finditer(code):
            name, tail = m.group(1), m.group(3)
            guarded = tail[:1] in GUARD_CHARS and tail != ""
            if not guarded and MARKER not in raw:
                array_findings.append(
                    (n, "B", f"{name}[{m.group(2)}]", raw.strip()[:96]))

        # ---- names referenced on this line ----------------------------
        for m in RE_REF.finditer(code):
            brace, name, idx, nxt = m.group(1), m.group(2), m.group(3), m.group(4)
            if idx:                              # arrays are Rule B's business
                continue
            if brace and nxt in GUARD_CHARS:     # ${V:-…} and friends
                continue
            if MARKER in raw:                    # deliberately unset — claimed
                continue                         # on the line, with a reason
            used.setdefault(name, (n, raw.strip()[:96]))

    findings = []
    for name, (n, text) in sorted(used.items(), key=lambda kv: kv[1][0]):
        if name in SHELL_PROVIDED or name.isdigit():
            continue
        first_assign = assigned.get(name)
        if first_assign is None or first_assign > n:
            where = f"first assigned line {first_assign}" if first_assign else "never assigned in file"
            findings.append((n, "A", name, f"{text}   [{where}]"))
    findings.extend(array_findings)
    findings.sort(key=lambda f: f[0])
    return findings


def report(path: Path, findings) -> None:
    rel = path.name
    if not findings:
        print(f"  ✓ {rel}")
        return
    print(f"  ✗ {rel} — {len(findings)} finding(s)")
    for n, rule, name, text in findings:
        kind = ("used before assignment" if rule == "A"
                else "array expansion with no :- / + guard and no `# unbound-ok:` reason")
        print(f"      line {n}  [{rule}] ${name}  {kind}")
        print(f"               {text}")


def prove() -> int:
    """Run against the two REAL historical bugs, pulled from git. This is the
    only evidence that matters: synthetic cases prove a checker catches what it
    was written to catch."""
    # Assert the SPECIFIC variable, never merely "some findings". A historical
    # file has other unannotated sites, so "9 findings" would pass even if the
    # real bug were missed — a proof aimed at the wrong thing
    # (claude-anti-patterns #68). Name the variable and the rule.
    cases = [
        ("dd10778^", "the ${WARNINGS[*]} array bug (2026-05-18)", "WARNINGS[*]", "B"),
        ("08a2275", "the $LIMITLESS_STACK_HOME scalar bug (2026-08-23)", "LIMITLESS_STACK_HOME", "A"),
    ]
    ok = True
    print("\nproving against real history\n")
    for rev, label, want_name, want_rule in cases:
        try:
            blob = subprocess.run(
                ["git", "-C", str(VAULT), "show", f"{rev}:tools/limitless-preflight.sh"],
                capture_output=True, text=True, check=True).stdout
        except subprocess.CalledProcessError:
            print(f"  ? {rev} — not reachable from this clone; SKIPPED")
            continue
        tmp = Path("/tmp") / f".unbound-prove-{rev.replace('^','_')}.sh"
        tmp.write_text(blob)
        found = scan(tmp)
        tmp.unlink()
        hits = [f for f in found if f[2] == want_name and f[1] == want_rule]
        good = bool(hits)
        ok &= good
        print(f"  {'✓' if good else '✗'} {rev}: {label}")
        if good:
            n, rule, name, text = hits[0]
            print(f"      caught it — line {n} [{rule}] ${name}")
            print(f"        {text[:88]}")
        else:
            print(f"      MISSED ${want_name} (rule {want_rule}). "
                  f"{len(found)} other finding(s) — irrelevant to this proof.")
    cur = VAULT / "tools" / "limitless-preflight.sh"
    found = scan(cur)
    good = not found
    ok &= good
    print(f"  {'✓' if good else '✗'} current limitless-preflight.sh: expected CLEAN, got {len(found)}")
    for n, rule, name, _ in found[:5]:
        print(f"        line {n} [{rule}] ${name}")

    # POSITIVE CONTROL. "0 findings" and "scanned nothing" look identical from
    # the outside, and this scanner skips heredocs and multi-line quoted spans —
    # exactly the machinery that could go blind after an edit. So plant a bug in
    # a COPY of today's file and require it to be found. Without this, a regex
    # change that silently disabled the scan would still report a clean sweep.
    text = cur.read_text().split("\n")
    for i, line in enumerate(text):
        if line.startswith("# ── Project manifest"):
            text.insert(i, ': "$__COVERAGE_PROBE_MUST_BE_SEEN"')
            break
    probe = Path("/tmp/.unbound-coverage-probe.sh")
    probe.write_text("\n".join(text))
    seen = any(f[2] == "__COVERAGE_PROBE_MUST_BE_SEEN" for f in scan(probe))
    probe.unlink()
    ok &= seen
    print(f"  {'✓' if seen else '✗'} positive control: a planted bug in today's file IS detected"
          f"{'' if seen else '  — THE SCANNER IS BLIND, do not trust a clean sweep'}")
    print()
    return 0 if ok else 1


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--prove" in sys.argv:
        return prove()
    targets = [Path(a) for a in args] or sorted((VAULT / "tools").glob("*.sh"))
    if not targets:
        print("no shell files found", file=sys.stderr)
        return 2
    total = 0
    print(f"\nshell unbound-variable check — {len(targets)} file(s)\n")
    for p in targets:
        findings = scan(p)
        total += len(findings)
        report(p, findings)
    print(f"\n  {total} finding(s)\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
