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


def check_readme_migrations():
    """A2. Same parity check against README.md — the fresh-clone entry point.

    Added 2026-08-23: the CLAUDE.md table was correct and passed, while README's
    stopped at 011 with 15 files on disk. Check A only ever read one file, so a
    green there said nothing about the document a new reader opens first.
    """
    mig_dir = os.path.join(HUB, "migrations")
    if not os.path.isdir(mig_dir):
        note_skip("README migration table: migrations/ not found")
        return
    if not os.path.exists(HUB_README):
        note_skip(f"README migration table: {HUB_README} not readable")
        return
    txt = _read(HUB_README)
    claimed = set(_MIG_ROW.findall(txt))
    if not claimed:
        note_skip("README migration table: no table rows parsed — nothing to compare "
                  "(coverage floor: not reporting a green on an empty set)")
        return
    files = {os.path.basename(f) for f in glob.glob(os.path.join(mig_dir, "*.sql"))
             if _MIG_FILE.match(os.path.basename(f))}
    for name in sorted(files - claimed):
        add(f"migration {name} exists but is NOT in the README migration table",
            f"add its row to {HUB}/README.md (CLAUDE.md's table is checked separately "
            f"and can be correct while this one rots)")
    for name in sorted(claimed - files):
        add(f"README migration table lists {name} but no such file exists",
            f"correct the row in {HUB}/README.md")


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



# ============================================================================
# Checks D/E/F added 2026-08-23 after a sweep found 25 rot sites in one day.
# Each maps to a failure that ACTUALLY happened, not a hypothetical:
#   D  `/pinecone` was cited as a route in 4 documents; it is a sidebar LABEL
#      whose path is `/search`. Navigating to it hits <ComingSoon/>.
#   E  Two trust anchors disagreed on the migration count (11 vs 15). A session
#      trusting the low number writes migrations/012_*.sql on top of an existing
#      012.
#   F  "Matt has Fly.io access" lived in 7 places and got flipped 5 times: one
#      bad probe poisons one page, and the next session finds a different page
#      first. A fact asserted in 7 places has no truth value, only a majority
#      vote that changes with reading order.
#
# All three obey this file's stated design principle: CONSERVATIVE about false
# positives (a noisy check trains humans to ignore the preflight), HONEST about
# false silence (anything unverifiable is an explicit SKIP, never a silent pass).
# ============================================================================

HUB_APP  = os.path.join(HUB, "client", "src", "App.jsx")
HUB_NAV  = os.path.join(HUB, "client", "src", "components", "shell", "nav-config.js")
HUB_README = os.path.join(HUB, "README.md")
WIKI_HUB_PAGE = os.path.join(VAULT, "wiki", "apps", "limitless-stack-hub.md")

# Documents that speak about the Hub in the present tense and are read as truth.
_HUB_DOCS = [(HUB_CLAUDE, "Hub CLAUDE.md"), (HUB_README, "Hub README.md"),
             (WIKI_HUB_PAGE, "wiki apps/limitless-stack-hub.md")]

# A mention is EXCUSED when the line explicitly says the thing is not a route.
# Deliberately requires an EXPLICIT marker: an earlier draft excused any line
# that merely contained some other real route, and that would have excused the
# original bug verbatim ("- **Memory**: `/wiki`, `/pinecone`, `/notebooks`").
_ROUTE_EXCUSE = ("label", "not a route", "corrected", "renamed", "phantom",
                 "does not exist", "falls through")


def _hub_routes():
    """Real routes = the cases the Hub router actually handles."""
    if not os.path.exists(HUB_APP):
        return None
    return set(re.findall(r'case\s+"(/[a-z0-9/-]*)"', _read(HUB_APP)))


def _nav_pairs():
    """[(label, path)] from the sidebar config."""
    if not os.path.exists(HUB_NAV):
        return None
    txt = _read(HUB_NAV)
    return re.findall(r'label:\s*"([^"]+)"[^}]*?path:\s*"(/[a-z0-9/-]*)"', txt)


def check_phantom_routes():
    """D. A sidebar LABEL whose path differs, cited in a doc as if it were a route.

    Scoped to exactly that class on purpose. A general "every backticked /x must
    be a route" check was PROTOTYPED AND REJECTED 2026-08-23: measured against
    the live docs it produced 3 false positives (`/compare`, `/page`, `/user` —
    GitHub-API path fragments) while excusing the real bug. This version is
    self-maintaining: it derives the phantom set from nav-config, so the NEXT
    label/path divergence is caught with no code change.
    """
    routes = _hub_routes()
    pairs = _nav_pairs()
    if routes is None or pairs is None:
        note_skip("phantom routes: Hub client source not readable (App.jsx / nav-config.js)")
        return
    if not routes or not pairs:
        note_skip("phantom routes: parsed 0 routes or 0 nav entries — refusing to report a green "
                  "on an empty set (coverage floor)")
        return
    phantoms = {}
    for label, path in pairs:
        guess = "/" + re.sub(r"[^a-z0-9-]", "", label.lower())
        if guess != path and guess not in routes and len(guess) > 2:
            phantoms[guess] = (label, path)
    if not phantoms:
        return
    for doc, name in _HUB_DOCS:
        if not os.path.exists(doc):
            note_skip(f"phantom routes: {name} not readable")
            continue
        for i, line in enumerate(_read(doc).splitlines(), 1):
            low = line.lower()
            if any(tok in low for tok in _ROUTE_EXCUSE):
                continue
            for ph, (label, path) in phantoms.items():
                if f"`{ph}`" in line:
                    add(f"{name}:{i} cites `{ph}` as a route, but that is the sidebar LABEL "
                        f"\"{label}\" — the real path is `{path}`",
                        f"use `{path}`, or say explicitly on that line that `{ph}` is a label "
                        f"(the checker excuses lines containing: {', '.join(_ROUTE_EXCUSE)})")


_NUMWORD = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
            "nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,
            "fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19,"twenty":20}


def check_prose_counts():
    """E. Counts stated in prose vs the count on disk.

    Only two nouns are checked — `migrations` and `routes`/`router cases` — both
    of which broke on 2026-08-23. `pages` is deliberately NOT checked: the vault
    says "150 pages" about the WIKI and the Hub says "17 pages" about itself, and
    no regex can tell those apart without guessing. Leaving it out is the
    conservative call, not an oversight.
    """
    mig_dir = os.path.join(HUB, "migrations")
    real_mig = len([f for f in glob.glob(os.path.join(mig_dir, "*.sql"))
                    if _MIG_FILE.match(os.path.basename(f))]) if os.path.isdir(mig_dir) else None
    routes = _hub_routes()
    real_routes = len(routes) if routes else None
    if real_mig is None and real_routes is None:
        note_skip("prose counts: neither migrations/ nor App.jsx readable")
        return
    pat = re.compile(r"\b(\d{1,3}|" + "|".join(_NUMWORD) + r")\s+(migrations|routes|router cases)\b", re.I)
    for doc, name in _HUB_DOCS:
        if not os.path.exists(doc):
            continue
        for i, line in enumerate(_read(doc).splitlines(), 1):
            if "corrected" in line.lower() or "~~" in line:
                continue  # an explicit correction may quote the old number
            for raw, noun in pat.findall(line):
                n = _NUMWORD.get(raw.lower(), None)
                if n is None:
                    try: n = int(raw)
                    except ValueError: continue
                noun_l = noun.lower()
                if noun_l == "migrations" and real_mig is not None and n != real_mig:
                    add(f"{name}:{i} claims {raw} migrations; migrations/ holds {real_mig}",
                        f"correct the number in {name} (a low count makes the next session "
                        f"collide on an existing migration file)")
                elif noun_l in ("routes", "router cases") and real_routes is not None and n != real_routes:
                    add(f"{name}:{i} claims {raw} {noun}; App.jsx handles {real_routes}",
                        f"correct the number in {name}, or re-count if the router changed")


# F. Facts that are NOT derivable from the system — they are facts about the
# world — get exactly ONE owner page. Everyone else links; nobody restates.
# Seeded with the Fly-access fact, which flipped five times across seven pages.
_CANONICAL_FACTS = [
    {
        "id": "fly-access",
        "owner": "wiki/concepts/limitless-stack.md",
        "link": "[[concepts/limitless-stack]]",
        "markers": [r"fly\.?io access", r"\bfly access\b"],
        # log.md is append-only history (restating a fact there is CORRECT — it
        # records what was believed on a date); the rollup is machine-generated.
        "exempt": ["wiki/log.md", "wiki/synthesis/hub-handoffs-rollup.md",
                   "wiki/concepts/limitless-stack.md"],
    },
]


def check_canonical_facts():
    """F. Warn when a registered fact is restated somewhere that does not link home."""
    wiki_root = os.path.join(VAULT, "wiki")
    if not os.path.isdir(wiki_root):
        note_skip("canonical facts: wiki/ not found")
        return
    files = glob.glob(os.path.join(wiki_root, "**", "*.md"), recursive=True)
    if not files:
        note_skip("canonical facts: scanned 0 wiki files — refusing to report a green on an "
                  "empty set (coverage floor)")
        return
    for fact in _CANONICAL_FACTS:
        owner = fact["owner"]
        if not os.path.exists(os.path.join(VAULT, owner)):
            note_skip(f"canonical fact '{fact['id']}': owner page {owner} missing")
            continue
        pats = [re.compile(m, re.I) for m in fact["markers"]]
        offenders = []
        for path in sorted(files):
            rel = os.path.relpath(path, VAULT)
            if any(rel == e or rel.endswith(e) for e in fact["exempt"]):
                continue
            txt = _read(path)
            hits = [m for p in pats for m in p.finditer(txt)]
            if not hits:
                continue
            # PROXIMITY, not file-presence. An earlier draft accepted the link
            # anywhere in the file; a mutation test (2026-08-23) showed that a
            # long page linking to the owner for an UNRELATED reason bought a
            # free pass on restating the fact — the check produced real findings
            # on the baseline while being toothless on the case it exists for.
            # The link must sit beside the restatement to excuse it.
            if all(fact["link"] in txt[max(0, m.start() - 400):m.end() + 400] for m in hits):
                continue  # every restatement points home — acceptable
            offenders.append(rel)
        # ONE finding per fact, not one per page. MEASURED 2026-08-23: a
        # registered fact is mentioned on 9-14 wiki pages, so per-page findings
        # would fire a 9-14 warning BURST the moment anyone registers a new
        # fact — and five casual registrations would be a ~50-warning wall.
        # That is precisely the cry-wolf failure this file's design principle
        # names. Aggregating keeps the signal and caps the noise at 1 per fact.
        if offenders:
            shown = ", ".join(offenders[:3])
            more = f" (+{len(offenders) - 3} more)" if len(offenders) > 3 else ""
            add(f"{len(offenders)} page(s) state the '{fact['id']}' fact without linking to its "
                f"owner page nearby: {shown}{more}",
                f"link {fact['link']} beside each mention instead of restating it — "
                f"owner page is {owner}. NOTE: registering a new fact typically surfaces "
                f"~9-14 sites; clean them in the same session you register it, or the next "
                f"session inherits a wall of warnings.")

def main():
    try:
        check_hub_migrations()
        check_readme_migrations()
        # Per-repo allowlists: only paths that DEFINITELY live in that repo.
        # Vault owns tools/ + the installed skills; the Hub owns its app source
        # and its own docs/ (but docs/migrations/* is an OF-repo path — excluded
        # via _SKIP_PATH).
        check_paths(VAULT_CLAUDE, VAULT, "vault", ("tools/", "~/.claude/skills/"))
        check_paths(HUB_CLAUDE, HUB, "Hub", ("server/", "api/", "client/", "migrations/", "docs/"))
        check_notebook_ids()
        check_phantom_routes()
        check_prose_counts()
        check_canonical_facts()
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
