#!/usr/bin/env python3.11
"""
trust-anchor-check.py — Loop 6 of the Limitless Stack: the TRUST-ANCHOR REALITY
INSPECTOR.

The CLAUDE.md files are the stack's trust anchors — every Claude session reads
them as ground truth. When they drift from reality (a migration table row whose
file was renamed; a doc that points at a file that moved; a notebook id that no
longer routes), the drift propagates as confidently-stated wrong facts. That is
the #12 / #14 / #33 failure class the wiki CLAUDE.md keeps re-learning by hand.

This mechanizes the checkable part of the end-of-session "refresh the trust
anchors" step. Three checks:

  A. Hub CLAUDE.md migration table  <->  migrations/*.sql files, compared by FULL
     FILENAME (not just the number) so a row whose file was renamed is caught.
     NOTE: this verifies table<->file PARITY. It does NOT (cannot, from here)
     verify a migration was actually APPLIED to prod — that needs DB reach.
  B. Backtick file-path claims that are SELF-REFERENTIAL to the repo (under a
     per-repo prefix allowlist) exist on disk.
  C. NotebookLM ids the vault CLAUDE.md presents as notebooks exist in the real
     routing config.

DESIGN PRINCIPLE: be CONSERVATIVE about false positives (a noisy check trains
humans to ignore the preflight — the cry-wolf failure Loop 5's audit hammered),
AND honest about false silence (a check that couldn't run must SAY so, never
report a green it didn't earn). Anything unverifiable (repo not cloned, config
unreadable) is emitted as an explicit SKIP, not a silent pass.

OUTPUT (stdout), one item per line:
    SKIP: <reason>            a dimension that could not be verified
    <message>\t<fix hint>    a drift finding (TAB-separated)
Exit code:
    0 = no DRIFT findings (there may still be SKIP lines)
    1 = at least one drift finding
    2 = the checker itself errored (message on stderr)

The preflight renders SKIP lines as a note and drift lines as warn()s; its green
line names only the dimensions that actually ran.
"""

import os
import re
import sys
import glob

VAULT = "/Users/matthewlavin/Claude code antigravity/obsidian "  # trailing space is intentional
HUB   = "/Users/matthewlavin/limitless-stack-hub"

VAULT_CLAUDE = os.path.join(VAULT, "CLAUDE.md")
HUB_CLAUDE   = os.path.join(HUB, "CLAUDE.md")

findings = []   # (message, fix)
skips    = []   # reason strings — dimensions that could not be verified


def add(message, fix):
    findings.append((message, fix))


def note_skip(reason):
    skips.append(reason)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


# -- Check A -- Hub migration table  <->  migrations/*.sql, by FULL FILENAME ----
_MIG_FILE = re.compile(r"^(\d{3,4}[_-][A-Za-z0-9_.-]+\.sql)$", re.I)
_MIG_ROW  = re.compile(r"^\|\s*`?(\d{3,4}[_-][A-Za-z0-9_.-]+\.sql)`?", re.I | re.M)


def check_hub_migrations():
    if not os.path.isdir(os.path.join(HUB, ".git")):
        note_skip(f"migration table: Hub repo not cloned at {HUB} (clone it to verify)")
        return
    mig_dir = os.path.join(HUB, "migrations")
    if not os.path.isdir(mig_dir):
        note_skip(f"migration table: {mig_dir} not found")
        return
    if not os.path.exists(HUB_CLAUDE):
        note_skip(f"migration table: {HUB_CLAUDE} not readable")
        return
    files = {os.path.basename(f) for f in glob.glob(os.path.join(mig_dir, "*.sql"))
             if _MIG_FILE.match(os.path.basename(f))}
    claimed = set(_MIG_ROW.findall(_read(HUB_CLAUDE)))
    for name in sorted(files - claimed):
        add(f"Hub migration file {name} exists but is NOT in the CLAUDE.md migration table",
            f"add/repair its row in {HUB}/CLAUDE.md (the #33 'code shipped, doc says pending' class)")
    for name in sorted(claimed - files):
        add(f"Hub CLAUDE.md migration table lists {name} but no such file exists in migrations/",
            f"correct the row in {HUB}/CLAUDE.md (renamed file?), or restore the migration")


# -- Check B -- self-referential backtick file-path claims exist --------------
_PATH_RE = re.compile(
    r"`([~A-Za-z0-9_.][~A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+\.(?:js|ts|tsx|sql|md|json|sh|py|yml|yaml))`"
)
# Substrings that mark a path as illustrative/template/cross-repo — never checked.
_SKIP_PATH = ("*", "{", "}", "<", ">", "YYYY", "MM-DD", "0NN", "/NN_", "jane-doe",
              "docs/migrations/")  # docs/migrations/* is an OpenFirehouse-repo path, not Hub-local


def check_paths(claude_path, repo_root, label, prefixes):
    if not os.path.exists(claude_path):
        note_skip(f"{label} file-path claims: {claude_path} not readable")
        return
    txt = _read(claude_path)
    seen = set()
    for raw in _PATH_RE.findall(txt):
        if raw in seen:
            continue
        seen.add(raw)
        if any(tok in raw for tok in _SKIP_PATH):
            continue
        if not any(raw.startswith(pfx) for pfx in prefixes):
            continue  # not a self-referential path we can authoritatively check
        p = os.path.expanduser(raw) if raw[0] in "~/" else os.path.join(repo_root, raw)
        if not os.path.exists(p):
            add(f"{label} CLAUDE.md references `{raw}` but that file does not exist on disk",
                f"fix the path in {claude_path}, or restore/rename the file it points to")


# -- Check C -- vault CLAUDE.md notebook ids exist in the routing config -------
def check_notebook_ids():
    if not os.path.exists(VAULT_CLAUDE):
        note_skip(f"notebook ids: {VAULT_CLAUDE} not readable")
        return
    config_ids = set()
    for cf in (os.path.join(VAULT, ".limitless-project.py"),
               os.path.join(VAULT, "tools", "notebooklm-wiki-refresh.py")):
        if os.path.exists(cf):
            t = _read(cf)
            config_ids |= set(re.findall(r"\b([0-9a-f]{8})\b", t))
            config_ids |= {u[:8] for u in re.findall(r"\b[0-9a-f]{8}-[0-9a-f-]{20,}", t)}
    if not config_ids:
        note_skip("notebook ids: routing config (.limitless-project.py / notebooklm-wiki-refresh.py) not readable")
        return
    txt = _read(VAULT_CLAUDE)
    checked = set()
    # Conservative: only a BACKTICK-WRAPPED 8-hex, with "notebook" in the 40 chars
    # before it, and no git-sha context word ("commit"/"sha"/"build") in the 15
    # chars before — so a backticked commit sha near the word "notebook" is not
    # mistaken for a notebook id.
    for m in re.finditer(r"`([0-9a-f]{8})`", txt):
        nid = m.group(1)
        if nid in checked:
            continue
        pre40 = txt[max(0, m.start() - 40):m.start()].lower()
        pre15 = txt[max(0, m.start() - 15):m.start()].lower()
        if "notebook" not in pre40:
            continue
        if any(w in pre15 for w in ("commit", "sha", "build")):
            continue
        checked.add(nid)
        if nid not in config_ids:
            add(f"vault CLAUDE.md references NotebookLM id `{nid}` (in a notebook context) but it is not in the routing config",
                "reconcile CLAUDE.md with .limitless-project.py / tools/notebooklm-wiki-refresh.py")


def main():
    try:
        check_hub_migrations()
        # Per-repo allowlists: only paths that DEFINITELY live in that repo.
        # Vault owns tools/ + the installed skills; the Hub owns its app source
        # and its own docs/ (but docs/migrations/* is an OF-repo path — excluded
        # via _SKIP_PATH).
        check_paths(VAULT_CLAUDE, VAULT, "vault", ("tools/", "~/.claude/skills/"))
        check_paths(HUB_CLAUDE, HUB, "Hub", ("server/", "api/", "client/", "migrations/", "docs/"))
        check_notebook_ids()
    except Exception as exc:  # never crash the preflight — degrade to exit 2
        sys.stderr.write(f"trust-anchor-check error: {exc}\n")
        return 2
    for reason in skips:
        print(f"SKIP: {reason}")
    for message, fix in findings:
        print(f"{message}\t{fix}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
