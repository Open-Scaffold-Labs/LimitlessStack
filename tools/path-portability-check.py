#!/usr/bin/env python3.11
"""path-portability-check.py — a machine-specific path may not be UNCONDITIONAL.

WHY THIS EXISTS. On 2026-08-24 three separate tools were found assuming the
machine they were authored on, and each one degraded to a polite "I can't check
that here" everywhere else:

  · limitless-preflight.sh   read $LIMITLESS_STACK_HOME 172 lines above its
                             default — fine in the author's shell, fatal in a
                             clean one; killed checks 4-7 of 7.
  · trust-anchor-check.py    hardcoded /Users/matthewlavin/... — skipped 8 of 8
                             checks in a Cowork sandbox and exited 0, while every
                             file it wanted sat a few directories away.
  · scan-capabilities.py     looked only at ~/.claude/skills — reported "0 skills"
                             in an environment with 18 skills mounted elsewhere.

Each was fixed as an INSTANCE. This is the CLASS, and it is the first line:
the shape cannot be committed, so it never reaches a run to be detected in.
(Anti-pattern #72, first clause — "exercised only in the shell that authored it".)

WHAT IS AND IS NOT A FINDING — this distinction is the whole design.

  FINDING      VAULT = "/Users/matthewlavin/..."          hard, no escape
  FINDING      for x in "/Users/matthewlavin/repo:Hub"    hard, no escape
  NOT a finding  X="${X:-/Users/matthewlavin/Repo}"       overridable default
  NOT a finding  os.environ.get("X", "/Users/...")        overridable default
  NOT a finding  # ...mentioned in a comment...           documentation
  NOT a finding  <line> # path-ok: <reason>               explicit waiver

An overridable default is portable: any environment can set the variable. That
is the pattern to KEEP, not to purge — flagging it would be the cry-wolf failure
this repo's own checkers are explicitly designed to avoid. Verified against all
23 tools: exactly 4 hard sites, 3 overridable ones correctly left alone.

USAGE
  tools/path-portability-check.py <file> [<file>...]
  exit 0 = clean · 1 = findings · 2 = bad invocation
"""

import os
import re
import sys

# Machine-specific absolute roots. Deliberately narrow: /usr, /var, /tmp and
# friends are the same everywhere and are not portability hazards.
MACHINE_PATH = re.compile(r'(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\)')

WAIVER = re.compile(r'#\s*path-ok:\s*\S')

# An occurrence is EXEMPT when it sits inside an overridable default. Both
# shells and Python have one idiomatic form each; anything else is unconditional.
OVERRIDABLE = (
    re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*:[-=]'),        # ${VAR:-...} / ${VAR:=...}
    re.compile(r'os\.environ\.get\s*\('),                   # os.environ.get("X", "/...")
    re.compile(r'os\.getenv\s*\('),
    re.compile(r'environ\.get\s*\('),
)


def strip_comment(line, is_py):
    """Remove a trailing comment so a documented path is not a finding.

    Quote-aware only to the degree it needs to be: a `#` inside a string is not
    a comment. Cheap scanner, no full parser — a false EXEMPTION here is the
    safe direction (the path is then judged on the code before it).
    """
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def scan(path):
    findings = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError as exc:
        print(f"path-portability: cannot read {path}: {exc}", file=sys.stderr)
        return None
    is_py = path.endswith(".py")
    # Track triple-quoted blocks. A path inside a docstring is DOCUMENTATION,
    # exactly like a `#` comment — and the first version of this file flagged
    # its OWN docstring three times, which is the cry-wolf failure it is meant
    # to help prevent. Runtime strings use single quotes, so `VAULT = "/Users/…"`
    # is still judged.
    in_block = None
    for n, raw in enumerate(lines, 1):
        # Blank out triple-quoted SPANS rather than skipping whole lines. Skipping
        # lines handled multi-line docstrings but not a one-liner, whose quoted
        # text stayed on a line that was still judged — caught by the `doc`
        # control before this shipped. Removing the span handles both, and keeps
        # any real code sharing the line.
        if is_py:
            out, i = [], 0
            while i < len(raw):
                if in_block:
                    idx = raw.find(in_block, i)
                    if idx < 0:
                        i = len(raw)
                        break
                    in_block, i = None, idx + 3
                    continue
                cands = [x for x in (raw.find('"""', i), raw.find("'''", i)) if x >= 0]
                if not cands:
                    out.append(raw[i:])
                    break
                nxt = min(cands)
                out.append(raw[i:nxt])
                in_block, i = raw[nxt:nxt + 3], nxt + 3
            raw_code = "".join(out)
        else:
            raw_code = raw
        if WAIVER.search(raw):
            continue
        code = strip_comment(raw_code, is_py)
        if not MACHINE_PATH.search(code):
            continue
        if any(p.search(code) for p in OVERRIDABLE):
            continue
        findings.append((n, raw.strip()[:120]))
    return findings


def main(argv):
    if not argv:
        print("usage: path-portability-check.py <file> [<file>...]", file=sys.stderr)
        return 2
    total, scanned = 0, 0
    for path in argv:
        res = scan(path)
        if res is None:
            return 2
        scanned += 1
        for n, text in res:
            if total == 0:
                print("  machine-specific path in UNCONDITIONAL code:")
            print(f"      {os.path.basename(path)}:{n}  {text}")
            total += 1
    # Coverage floor: a sweep that read nothing must not report clean.
    if scanned == 0:
        print("path-portability: scanned 0 files — nothing was checked.", file=sys.stderr)
        return 2
    if total:
        print()
        print("  A hardcoded machine path makes the tool inert everywhere else —")
        print("  it does not fail loudly, it degrades to 'I can't check that here'.")
        print("  Fix by DISCOVERY (derive from __file__ / $0) or by an overridable")
        print("  default: VAR=\"${VAR:-/the/path}\" · os.environ.get(\"VAR\", \"/the/path\")")
        print("  If a line is genuinely fixed to one machine, say why:")
        print("      THE_LINE   # path-ok: <reason>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
