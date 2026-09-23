#!/usr/bin/env python3
"""authorship-guard.py — in a shared vault, nobody changes what someone else wrote.

The rule (Matt, 2026-09-23): everyone can read everything and ADD anything; a person's
own writing can only be changed or removed by that person. Anyone else who wants it
changed files a SUGGESTION, and the owner approves it and makes the change themselves.

Opt-in per repo: it does nothing unless `.authors.json` exists at the repo root. A
personal vault never needs it; a vault shared by several people turns it on.

Who owns a line:
  * PATH-OWNED files belong to one person outright — `members/<login>/**` and
    `wiki/my-tasks/<login>.md` (and `<login>-archive.md`). Only that person may add to,
    change or delete them.
  * Every other line belongs to whoever wrote it, as `git blame` records it. Adding new
    lines anywhere is always allowed; changing or removing someone else's line is not.
  * Not owned at all: machine-written files (`exempt_paths`), lines inside a
    `BEGIN GENERATED` ... `END GENERATED` block, and lines matching
    `exempt_line_patterns` (e.g. a page's `updated:` date).

Modes:
  authorship-guard.py --staged          the commit being made (pre-commit hook)
  authorship-guard.py --commit <sha>    one existing commit vs its first parent (CI)
  authorship-guard.py --range A..B      every commit in a range (CI, one push)
  --json                                machine-readable result (CI)
  --config <file>                       use this authors file instead of the repo's (replays, tests)
Exit: 0 clean / not enabled · 1 violation(s) · 2 could not run (reported, never silent).
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

GENERATED_BEGIN = re.compile(r"BEGIN GENERATED")
GENERATED_END = re.compile(r"END GENERATED")
PATH_OWNED = [
    re.compile(r"^members/(?P<login>[^/]+)/"),
    re.compile(r"^wiki/my-tasks/(?P<login>[^/]+?)(?:-archive)?\.md$"),
]
NOREPLY = re.compile(r"^(?:\d+\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$")


def git(*args, check=True):
    # errors="replace": a vault holds text in any encoding (a Windows curly quote broke the
    # first full-history replay). A decode error must never become a blocked commit.
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def repo_root():
    # rstrip("\n") only: a folder name may legitimately END IN A SPACE (the shared vault's
    # does), and .strip() silently turned that into a path that does not exist.
    return git("rev-parse", "--show-toplevel").rstrip("\n")


CONFIG_OVERRIDE = None


def load_config(root, ref=None):
    """Read .authors.json from the working tree (staged mode) or from a commit (CI)."""
    try:
        if CONFIG_OVERRIDE:
            text = open(CONFIG_OVERRIDE).read()
        else:
            text = git("show", f"{ref}:.authors.json") if ref else open(os.path.join(root, ".authors.json")).read()
    except (OSError, RuntimeError):
        return None
    cfg = json.loads(text)
    email_to_login = {}
    for login, person in cfg.get("people", {}).items():
        for e in person.get("emails", []):
            email_to_login[e.strip().lower()] = login
    cfg["_email_to_login"] = email_to_login
    return cfg


def person_for(email, cfg):
    e = (email or "").strip().strip("<>").lower()
    if e in cfg["_email_to_login"]:
        return cfg["_email_to_login"][e]
    m = NOREPLY.match(e)
    if m and m.group("login") in cfg.get("people", {}):
        return m.group("login")
    return f"unknown <{e}>"


def path_owner(path):
    for rx in PATH_OWNED:
        m = rx.match(path)
        if m:
            return m.group("login")
    return None


def is_exempt_path(path, cfg):
    return any(fnmatch.fnmatch(path, pat) for pat in cfg.get("exempt_paths", []))


def generated_lines(text):
    """1-based line numbers that sit inside a BEGIN/END GENERATED block (markers included)."""
    inside, out = False, set()
    for i, line in enumerate(text.splitlines(), 1):
        if GENERATED_BEGIN.search(line):
            inside = True
        if inside:
            out.add(i)
        if GENERATED_END.search(line):
            inside = False
    return out


def changed_files(base, target):
    """(status, old_path, new_path) for base -> target; target None = the index."""
    args = ["diff", "--no-renames", "--name-status", "-z"]
    args += ([base, target] if target else ["--cached", base])
    parts = [p for p in git(*args).split("\0") if p]
    out = []
    i = 0
    while i < len(parts):
        status = parts[i][0]
        path = parts[i + 1]
        out.append((status, path))
        i += 2
    return out


def removed_old_lines(base, target, path):
    """Old-side line numbers removed or rewritten by the change (from a -U0 diff)."""
    args = ["diff", "--no-renames", "-U0"]
    args += ([base, target] if target else ["--cached", base])
    diff = git(*args, "--", path)
    lines = []
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", diff, re.M):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        lines.extend(range(start, start + count))
    return lines


def is_binary(base, target, path):
    args = ["diff", "--no-renames", "--numstat"]
    args += ([base, target] if target else ["--cached", base])
    out = git(*args, "--", path).strip()
    return out.startswith("-\t-\t")


def blame(base, path, line_numbers):
    """{line_no: (author_email, text)} for the given old-side lines at `base`."""
    if not line_numbers:
        return {}
    ranges, start, prev = [], None, None
    for n in sorted(set(line_numbers)):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev)); start = prev = n
    ranges.append((start, prev))
    args = ["blame", "--line-porcelain"]
    for a, b in ranges:
        args += ["-L", f"{a},{b}"]
    out = git(*args, base, "--", path)
    result, cur_email, cur_line = {}, None, None
    for row in out.splitlines():
        if re.match(r"^[0-9a-f]{40} \d+ \d+", row):
            cur_line = int(row.split()[2])
        elif row.startswith("author-mail "):
            cur_email = row[len("author-mail "):]
        elif row.startswith("\t"):
            result[cur_line] = (cur_email, row[1:])
    return result


def check(base, target, actor, cfg):
    """Violations for the change base -> target (target None = staged) made by `actor`."""
    violations = []
    line_patterns = [re.compile(p) for p in cfg.get("exempt_line_patterns", [])]
    for status, path in changed_files(base, target):
        if is_exempt_path(path, cfg):
            continue
        owner = path_owner(path)
        if owner is not None:
            if owner != actor:
                violations.append({"path": path, "owner": owner, "lines": "whole file",
                                   "why": f"{path} belongs to {owner}; only {owner} can write to it"})
            continue
        if status == "A":
            continue  # a brand-new file: nothing of anyone else's is touched
        if is_binary(base, target, path):
            # No lines to blame: a binary file belongs to whoever first added it.
            adder = git("log", "--diff-filter=A", "--format=%ae", base, "--", path).strip().splitlines()
            who = person_for(adder[-1], cfg) if adder else actor
            if who != actor:
                violations.append({"path": path, "owner": who, "lines": "whole file (binary)",
                                   "why": f"changes a file {who} added"})
            continue
        old_lines = removed_old_lines(base, target, path)
        if not old_lines:
            continue  # pure additions
        try:
            old_text = git("show", f"{base}:{path}")
        except RuntimeError:
            continue
        gen = generated_lines(old_text)
        owners = {}
        for n, (email, text) in blame(base, path, [n for n in old_lines if n not in gen]).items():
            if any(p.search(text) for p in line_patterns):
                continue
            who = person_for(email, cfg)
            if who != actor:
                owners.setdefault(who, []).append(n)
        for who, nums in sorted(owners.items()):
            violations.append({"path": path, "owner": who, "lines": nums,
                               "why": f"changes {len(nums)} line(s) {who} wrote"})
    return violations


def origin_slug():
    url = git("remote", "get-url", "origin", check=False).strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else "<owner>/<repo>"


def report(violations, actor, header):
    print(header)
    for v in violations:
        lines = v["lines"] if isinstance(v["lines"], str) else ", ".join(map(str, v["lines"][:12])) + (" ..." if len(v["lines"]) > 12 else "")
        print(f"  ✗ {v['path']} — {v['why']} (lines: {lines})")
    owners = sorted({v["owner"] for v in violations if not v["owner"].startswith("unknown")})
    if any(v["owner"].startswith("unknown") for v in violations):
        print("\n  Some lines were written by an identity not in .authors.json — add that email to the right person first.")
    if owners:
        print("\n  This is someone else's writing. Instead of changing it, send the owner a suggestion:")
        for o in owners:
            print(f"    gh issue create -R {origin_slug()} --assignee {o} \\\n"
                  f"      --title \"[Suggestion] <what should change>\" --body \"<the change and why>\"")
        print("  The owner approves it and makes the change themselves. Your own additions can be committed separately.")


def main(argv):
    global CONFIG_OVERRIDE
    as_json = "--json" in argv
    if "--config" in argv:
        CONFIG_OVERRIDE = os.path.abspath(argv[argv.index("--config") + 1])
    try:
        root = repo_root()
        os.chdir(root)
        if "--staged" in argv:
            cfg = load_config(root)
            if cfg is None:
                return 0
            has_head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0
            if not has_head:
                return 0  # first commit of a repo: nothing of anyone's exists yet
            actor = person_for(git("config", "user.email").strip(), cfg)
            v = check("HEAD", None, actor, cfg)
            if v:
                report(v, actor, f"\nauthorship: this commit (as {actor}) changes other people's writing")
                return 1
            return 0
        shas = []
        if "--commit" in argv:
            shas = [argv[argv.index("--commit") + 1]]
        elif "--range" in argv:
            shas = [s for s in git("rev-list", "--reverse", "--no-merges", argv[argv.index("--range") + 1]).split() if s]
        else:
            print(__doc__); return 2
        all_v = []
        for sha in shas:
            cfg = load_config(root, f"{sha}^") or load_config(root, sha)
            if cfg is None:
                continue
            actor = person_for(git("log", "-1", "--format=%ae", sha).strip(), cfg)
            parent = git("rev-parse", f"{sha}^", check=False).strip()
            if not parent:
                continue
            for v in check(parent, sha, actor, cfg):
                v.update({"commit": sha, "actor": actor,
                          "subject": git("log", "-1", "--format=%s", sha).strip()})
                all_v.append(v)
        if as_json:
            print(json.dumps(all_v, indent=2))
        elif all_v:
            for sha in dict.fromkeys(v["commit"] for v in all_v):
                vs = [v for v in all_v if v["commit"] == sha]
                report(vs, vs[0]["actor"], f"\nauthorship: commit {sha[:10]} ({vs[0]['actor']}) changed other people's writing")
        return 1 if all_v else 0
    except Exception as e:  # never silently pass: an error is reported and blocks
        print(f"authorship-guard: could not run — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
