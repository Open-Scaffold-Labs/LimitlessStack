#!/usr/bin/env python3.11
"""
Keep the OpenScaffold NotebookLM notebooks in sync with the vault.

Multiple notebooks are maintained:
  * Per-project notebooks (f376f6e8, 26a8db12, 9c8f3df0, 0a072ead) — own the
    individual vertical-app wiki pages (wiki/apps/<app>.md).
  * cdaa7a43 (OpenScaffold Wiki) — default bucket: everything in wiki/*.md
    that isn't routed to a per-project notebook.
  * ab4b7ccb (Limitless Stack Hub) — curated 5-file reminder layer (untouched
    by the routing logic; still uses its own allowlist).

Routing: NOTEBOOK_ROUTES is an ordered list of (path_prefix, notebook_id, ...)
entries. For each wiki file, the FIRST matching prefix wins; files matching
no route fall through to DEFAULT_ROUTE (cdaa7a43).

Usage:
    python3 tools/notebooklm-wiki-refresh.py                      # sync every route + reminder
    python3 tools/notebooklm-wiki-refresh.py --seed               # first-time / post-migration: match existing notebook sources by title, write all state files
    python3 tools/notebooklm-wiki-refresh.py --dry-run            # show what would happen, do nothing
    python3 tools/notebooklm-wiki-refresh.py --only firehazmat    # run only one route
    python3 tools/notebooklm-wiki-refresh.py --only all-projects  # run all per-project routes, skip default + reminder

State files at tools/.notebooklm-<label>-state.json map path -> {mtime, source_id}.
Notebook IDs are hard-coded below; change them if you replicate this to another vault.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
WIKI = VAULT / "wiki"
TOOLS = Path(__file__).resolve().parent

# ── Routing table ─────────────────────────────────────────────────────────
# (path_prefix, notebook_id, state_label, display_label)
# First-match-wins. Paths are matched as string prefixes against the
# vault-relative posix path. Files matching no route fall through to
# DEFAULT_ROUTE. To add a new per-project notebook, append an entry here
# (more specific prefixes should come before more general ones).
NOTEBOOK_ROUTES = [
    ("wiki/apps/firehazmat.md",       "f376f6e8-0c5c-4a29-95ce-44e85fbf7b62", "firehazmat",       "firehazmat"),
    ("wiki/apps/openchiropractor.md", "26a8db12-1543-4567-944d-c64a0d338acc", "openchiropractor", "openchiropractor"),
    ("wiki/apps/openfirehouse.md",    "9c8f3df0-5ebe-4523-85c2-dfdcf4e7dd02", "openfirehouse",    "openfirehouse"),
    ("wiki/apps/opensalon.md",        "0a072ead-e919-414a-80f7-27d5f1487afc", "opensalon",        "opensalon"),
    ("wiki/apps/the-match.md",        "e9337dea-f7cd-4fba-aabc-621d15ecc336", "the-match",        "the-match"),
    ("wiki/synthesis/hub-",           "ca083f4f-afd8-438a-9da6-339dec7c87f8", "hub",              "hub"),
]
# Fallback: (notebook_id, state_label, display_label)
DEFAULT_ROUTE = ("cdaa7a43-774e-4113-8288-207669dd981f", "wiki", "wiki")

# ── Ignored notebooks ─────────────────────────────────────────────────────
# Notebooks that exist in NotebookLM but are intentionally NOT routed by this
# script — research/reference buckets curated manually, archived experiments,
# or empty test notebooks. The preflight's notebook-coverage check uses this
# list to suppress orphan warnings. To START routing one of these, move it
# from here to NOTEBOOK_ROUTES.
#
# Contract: every notebook returned by `notebooklm list` MUST appear in one of
# {NOTEBOOK_ROUTES, DEFAULT_ROUTE, REMINDER_NOTEBOOK_ID, IGNORED_NOTEBOOKS}.
# That contract closes the "TheMatch silently unrouted for weeks" gap caught
# 2026-04-29 — see wiki/log.md for the schema entry.
IGNORED_NOTEBOOKS = {
    "733f98ef-ed33-42ca-a549-f6fc1731d5b5": "OpenScaffold Architecture (curated DOCX reference, not wiki-mirrored)",
    "1a0a0c47-e862-4fac-be42-70b75e0f883c": "OpenScaffold Business (curated DOCX reference, not wiki-mirrored)",
    "9830f04f-e29a-4c31-a758-d62867a9199f": "ERG Research (curated PDF reference)",
    "f386d513-5a6c-44e0-9a27-3d74340ebda6": "(untitled) empty test notebook",
    "75e0f097-9343-4a89-939b-1e1d9fd205cc": "(untitled) empty test notebook",
}

PROJECT_LABELS = [r[2] for r in NOTEBOOK_ROUTES]  # ["firehazmat", "openchiropractor", ..., "hub"]

# ── Exclusion list ────────────────────────────────────────────────────────
# Files matching any of these prefixes are NOT mirrored to ANY notebook —
# not a per-project notebook, not the default cdaa7a43 bucket, not the
# reminder. These are wiki summary pages whose underlying source material
# is already represented in a per-project notebook via the raw repo files
# (e.g., wiki/sources/firehazmat-claude-md-2026-04-14.md summarises the
# FireHazmat repo's CLAUDE.md, which is already a source in f376f6e8).
# Listing them here would create redundant retrieval surface area.
# Decision recorded 2026-04-21 (see synthesis/notebook-architecture-rebuild
# follow-up: "group (a) — option 3").
EXCLUDE_FROM_NOTEBOOKS = [
    "wiki/sources/firehazmat-",
    "wiki/sources/openchiropractor-",
    "wiki/sources/openfirehouse-",
    "wiki/sources/opensalon-",
    # Pruned from cdaa7a43 on 2026-05-03 to free slots under the 50-source
    # Standard-tier cap. Wiki files preserved (50+ inbound backlinks); they
    # just stop occupying NotebookLM slots. The dated snapshots are
    # superseded by current pages; erg-2024.md is FireHazmat-specific
    # and belongs in f376f6e8 (firehazmat) only.
    "wiki/sources/agentic-company-blueprint-2026-04-14.md",
    "wiki/sources/claude-code-karpathy-obsidian-video-2026-04-14.md",
    "wiki/synthesis/lint-2026-04-14.md",
    "wiki/sources/open-scaffold-docs-readme-2026-04-14.md",
    "wiki/sources/openscaffold-core-claude-md-2026-04-14.md",
    "wiki/sources/openscaffold-technical-architecture-v2-2026-04-14.md",
    "wiki/sources/paperclip-recommendation-memo-2026-04-06.md",
    "wiki/sources/paperclip-screenshots-memo-2026-04-07.md",
    "wiki/concepts/erg-2024.md",
]


def is_excluded(rel_path: str) -> bool:
    """True if `rel_path` matches any EXCLUDE_FROM_NOTEBOOKS prefix."""
    return any(rel_path.startswith(prefix) for prefix in EXCLUDE_FROM_NOTEBOOKS)


def state_file_for(label: str) -> Path:
    """Return tools/.notebooklm-<label>-state.json for a given route label."""
    return TOOLS / f".notebooklm-{label}-state.json"


def route_for_label(label: str) -> tuple[str, str, str]:
    """Return (notebook_id, state_label, display_label) for a given label."""
    if label == DEFAULT_ROUTE[1]:
        return (DEFAULT_ROUTE[0], DEFAULT_ROUTE[1], DEFAULT_ROUTE[2])
    for _prefix, nbid, state_label, display in NOTEBOOK_ROUTES:
        if state_label == label:
            return (nbid, state_label, display)
    raise KeyError(f"Unknown route label: {label}")


# ── Reminder notebook (ab4b7ccb) — curated 5-file allowlist ──────────────
# These are the operating-rule files mirrored into the Limitless Stack Hub
# reminder notebook. Editing this list is a deliberate choice: adding a file
# means it'll auto-upload on next sync; removing one does NOT auto-delete
# (sync_reminder never deletes — reminder scope is curated, deletes are manual).
REMINDER_NOTEBOOK_ID = "ab4b7ccb"
REMINDER_STATE_FILE = TOOLS / ".notebooklm-reminder-state.json"
REMINDER_FILES = [
    "CLAUDE.md",
    "wiki/synthesis/claude-anti-patterns.md",
    "wiki/concepts/limitless-stack.md",
    "wiki/concepts/paperclip.md",
    "wiki/apps/limitless-stack-hub.md",
]

# Some sources in ab4b7ccb were uploaded with renamed titles (e.g., the vault
# CLAUDE.md is stored as "vault-CLAUDE.md" to disambiguate from the Hub repo's
# CLAUDE.md). Map relative path -> title-in-notebook for these.
REMINDER_TITLE_ALIASES = {
    "CLAUDE.md": "vault-CLAUDE.md",
}


# ── Project manifest override ────────────────────────────────────────────
# If a `.limitless-project.py` manifest exists at $VAULT root, its NOTEBOOKLM
# block overrides the hardcoded defaults above. This is what lets the
# Limitless Stack tools work across multiple projects — each vault declares
# its own routing/reminder/ignored config in its manifest.
#
# Backwards-compat: no manifest → use the Hub-vault defaults defined above.
# Non-NOTEBOOKLM manifest blocks (PINECONE, SYNC_CHECK, etc.) are read by
# the bash preflight via a Python helper; this module only consumes
# NOTEBOOKLM. See `tools/limitless-project-loader.py` for the bash bridge.
def _load_manifest():
    """Load .limitless-project.py from $VAULT if present. Returns the
    manifest module's namespace dict, or {} on absence/error."""
    manifest_path = VAULT / ".limitless-project.py"
    if not manifest_path.exists():
        return {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_lsm", manifest_path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return {k: v for k, v in vars(m).items() if not k.startswith("_")}
    except Exception as e:
        print(f"WARNING: failed to load manifest at {manifest_path}: {e}",
              file=sys.stderr)
        return {}

_MANIFEST = _load_manifest()
_NB_MANIFEST = _MANIFEST.get("NOTEBOOKLM", {})

if "routes" in _NB_MANIFEST:
    NOTEBOOK_ROUTES = _NB_MANIFEST["routes"]
    PROJECT_LABELS = [r[2] for r in NOTEBOOK_ROUTES]
if "default" in _NB_MANIFEST:
    DEFAULT_ROUTE = _NB_MANIFEST["default"]
if "ignored" in _NB_MANIFEST:
    IGNORED_NOTEBOOKS = _NB_MANIFEST["ignored"]
if "exclude_paths" in _NB_MANIFEST:
    EXCLUDE_FROM_NOTEBOOKS = _NB_MANIFEST["exclude_paths"]
_REMINDER = _NB_MANIFEST.get("reminder", {})
if "notebook_id" in _REMINDER:
    REMINDER_NOTEBOOK_ID = _REMINDER["notebook_id"]
if "files" in _REMINDER:
    REMINDER_FILES = _REMINDER["files"]
if "title_aliases" in _REMINDER:
    REMINDER_TITLE_ALIASES = _REMINDER["title_aliases"]


def reminder_title_for(rel_path: str, basename: str) -> str:
    """Title to look up (or use when adding) in ab4b7ccb."""
    return REMINDER_TITLE_ALIASES.get(rel_path, basename)


# ── notebooklm-py CLI wrappers ───────────────────────────────────────────
def run_nb(args: list[str]) -> subprocess.CompletedProcess:
    """Run a notebooklm-py CLI command."""
    return subprocess.run(
        ["notebooklm"] + args,
        capture_output=True, text=True,
    )


def activate_notebook(nbid: str) -> None:
    """Set the current notebook context. Must be called before any source-* subcommand."""
    subprocess.run(["notebooklm", "use", nbid],
                   capture_output=True, text=True)


def check_auth() -> bool:
    """Verify NotebookLM auth is valid. Returns True if OK."""
    result = subprocess.run(["notebooklm", "auth", "check", "--test"],
                            capture_output=True, text=True)
    if result.returncode != 0 or "fail" in result.stdout.lower():
        print("AUTH EXPIRED — run 'notebooklm login' to re-authenticate.")
        return False
    return True


# ── State file helpers (per-route) ───────────────────────────────────────
def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            return {}
    return {}


def save_state(state_path: Path, state: dict) -> None:
    state_path.write_text(json.dumps(state, indent=2))


def iter_wiki_files():
    for p in WIKI.rglob("*.md"):
        if p.name.startswith("."):
            continue
        yield p


def parse_source_list(output: str) -> dict:
    """Parse `notebooklm source list --json` into {title: source_id}."""
    title_to_id: dict[str, str] = {}
    try:
        data = json.loads(output)
    except Exception:
        return title_to_id
    # data shape: either a list of sources or {"sources": [...]}
    sources = data if isinstance(data, list) else data.get("sources", [])
    for s in sources:
        sid = s.get("id") or s.get("source_id")
        title = s.get("title") or s.get("name")
        if sid and title:
            title_to_id[title] = sid
    return title_to_id


def cmd_add(path: Path) -> str | None:
    """Add a file, return source_id or None."""
    result = run_nb(["source", "add", str(path)])
    out = result.stdout + result.stderr
    m = re.search(r"Added source:\s+([0-9a-f-]+)", out)
    return m.group(1) if m else None


def cmd_refresh(source_id: str) -> bool:
    """⚠ NO-OP FOR FILE SOURCES. Kept for URL/Drive source compatibility only.

    Per the CLI help: `refresh  Refresh a URL/Drive source.` — for file-based
    (markdown/text) sources this silently succeeds with returncode=0 but does
    NOT replace the indexed content. Historically we trusted this and spent
    weeks with stale content in notebooks (see wiki/log.md 2026-04-24 entry).

    For file sources, use cmd_replace() instead — it does delete + add +
    content verification.
    """
    result = run_nb(["source", "refresh", source_id])
    return result.returncode == 0


def cmd_delete(source_id: str) -> bool:
    """Delete a source and VERIFY it's gone. Returns True ONLY if the source
    existed before the call AND is gone after. Distinguishes between "really
    deleted" and "never existed in the first place" — the latter returns
    False, because a caller checking the boolean shouldn't treat the two
    cases identically (e.g., in replace-flow: if old source was already gone,
    proceeding to add without knowing will create a ghost duplicate).

    Guards against three historical bugs:
      1. The CLI's `source delete` prompts interactively for confirmation
         unless `-y` is passed. subprocess.run can't answer the prompt,
         so the command hangs until timeout. Fix: always pass `-y`.
      2. Exit code 0 doesn't mean the source was actually removed. Fix:
         list sources post-delete and confirm the ID is gone.
      3. The CLI exits 0 even when the source_id doesn't match any existing
         source (it silently succeeds at "deleting nothing"). Fix: require
         the source to be present pre-call, and absent post-call.
    """
    def _list_ids() -> set[str] | None:
        r = run_nb(["source", "list", "--json"])
        if r.returncode != 0:
            return None
        try:
            data = json.loads(r.stdout)
            sources = data if isinstance(data, list) else data.get("sources", [])
            return {(s.get("id") or s.get("source_id")) for s in sources}
        except Exception:
            return None

    def _matches(live_ids: set[str]) -> bool:
        """True if source_id (or any ID starting with it, for partial matches) is present."""
        return any(
            live and (live == source_id or live.startswith(source_id))
            for live in live_ids
        )

    # Pre-check: source must exist before we try to delete it
    before = _list_ids()
    if before is None:
        return False  # can't confirm state
    if not _matches(before):
        return False  # source didn't exist; can't honestly say we deleted it

    # Do the delete
    result = run_nb(["source", "delete", "-y", source_id])
    if result.returncode != 0:
        return False

    # Post-check: source must be gone now
    after = _list_ids()
    if after is None:
        return False
    if _matches(after):
        return False  # delete didn't take effect
    return True


def _strip_for_compare(s: str) -> str:
    """Normalize markdown text for cross-NotebookLM-indexer comparison.
    The NotebookLM indexer strips or rewrites:
      - backticks (code spans)
      - markdown link brackets [text] and (url)
      - heading hash prefixes (#, ##, ###)
      - wiki-link double brackets [[target]] → target
      - emphasis markers (*, _, **)
      - collapses whitespace
    Apply the same transformations before comparing so our verify check
    doesn't throw false negatives on markdown formatting differences.
    """
    # Strip common markdown punctuation that NotebookLM normalizes away
    s = re.sub(r"[`*_]", "", s)          # code spans, bold, italic
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)  # wiki-links
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)  # markdown links
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)  # heading markers
    s = re.sub(r"\s+", " ", s).strip()   # whitespace collapse (last)
    return s


def _extract_content(remote_text: str) -> str:
    """Remove CLI preamble lines from a fulltext dump (safety net if the
    caller forgot to use -o; `-o` writes pure content). Strips lines that
    start with known CLI headers."""
    lines = remote_text.splitlines()
    keep = [ln for ln in lines if not (
        ln.startswith("Matched:") or ln.startswith("Source:")
        or ln.startswith("Title:") or ln.startswith("Characters:")
        or ln.startswith("Saved ") or ln.startswith("Error:")
    )]
    return "\n".join(keep)


def cmd_verify_content(source_id: str, path: Path, wait_retries: int = 5) -> bool:
    """Fetch the source's indexed fulltext and confirm it matches the local
    file closely enough. NotebookLM's indexer is LOSSY: it strips markdown
    punctuation (backticks, brackets, heading #'s, emphasis) AND drops
    chunks of content (observed ~5% shrinkage on a 17K-char file with code
    blocks). Any exact-match strategy on long strings will false-fail.

    Strategy: pick 5 short (30-char) markers evenly spaced through the
    normalized file, and require at least 3 of 5 to appear in the remote.
    This tolerates the indexer's lossiness while still catching genuine
    staleness (where 0–1 markers would match because the remote is an
    entirely different version).

    Polls with backoff (2,4,8,16,30s) to let indexing complete.
    """
    delays = [2, 4, 8, 16, 30]
    local_text = path.read_text()
    local_norm = _strip_for_compare(local_text)
    L = len(local_norm)
    if L < 150:
        # Too-short files: fall back to single full-content check
        if local_norm:
            def _check_short(remote_norm: str) -> bool:
                return local_norm in remote_norm or remote_norm in local_norm
        else:
            return True
    else:
        # Five markers at 20%, 40%, 60%, 80%, 95% of the file.
        positions = [0.20, 0.40, 0.60, 0.80, 0.95]
        markers = []
        for pct in positions:
            start = int(L * pct)
            chunk = local_norm[start:start + 30]
            if chunk:
                markers.append(chunk)
        if not markers:
            return True
        THRESHOLD = max(3, (len(markers) * 3) // 5)
        def _check_short(remote_norm: str) -> bool:
            hits = sum(1 for m in markers if m in remote_norm)
            return hits >= THRESHOLD

    for attempt in range(wait_retries):
        if attempt > 0:
            time.sleep(delays[min(attempt - 1, len(delays) - 1)])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tf:
            tmp_path = tf.name
        try:
            result = run_nb(["source", "fulltext", source_id, "-o", tmp_path])
            if result.returncode != 0:
                continue
            tp = Path(tmp_path)
            if not tp.exists() or tp.stat().st_size == 0:
                continue
            remote_text = _extract_content(tp.read_text())
            remote_norm = _strip_for_compare(remote_text)
            if _check_short(remote_norm):
                return True
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    return False


def _claim_unique_title(title: str, keep_sid: str) -> int:
    """After uploading a source, sweep any OTHER sources in the active
    notebook with the same title. Returns the number of ghost dupes deleted.

    Defends against the NotebookLM API's eventual-consistency window where
    cmd_replace's post-delete check shows the old source as gone, then the
    source reappears (or was never actually deleted) after cmd_add. Without
    this sweep, the result is two copies of the same file in the notebook
    despite cmd_replace's own delete+verify protection — observed twice in
    a single session 2026-04-29 (cdaa7a43/claude-anti-patterns.md and
    ab4b7ccb/CLAUDE.md), confirming the failure mode is real and not rare.

    Belt-and-suspenders: cmd_replace's first-line abort handles the
    optimistic case (delete is visible as gone → safe to add); this sweep
    handles the case where the API silently lied about the delete being
    visible. See anti-pattern #12 for the full failure mode.
    """
    listing = run_nb(["source", "list", "--json"])
    if listing.returncode != 0:
        return 0
    try:
        data = json.loads(listing.stdout)
    except Exception:
        return 0
    sources = data if isinstance(data, list) else data.get("sources", [])

    same_title = [s for s in sources if (s.get("title") or "") == title]
    if len(same_title) <= 1:
        return 0  # no ghost dupes to sweep

    swept = 0
    for s in same_title:
        sid = s.get("id") or s.get("source_id")
        if not sid or sid == keep_sid:
            continue  # the one we just uploaded — skip
        # cmd_delete has its own pre/post-check guards; trust its bool here.
        if cmd_delete(sid):
            swept += 1
    return swept


def cmd_replace(path: Path, old_source_id: str | None) -> tuple[str | None, bool]:
    """Replace a source's content: delete the old one (if any), add the new
    file, and verify the content actually landed in NotebookLM.

    Returns (new_source_id, verified). A non-None source_id with verified=False
    means the upload succeeded but the content check failed — almost always
    means NotebookLM hasn't finished indexing within the wait window. The
    caller should treat verified=False as a failure mode and either retry
    or flag it prominently.

    Triple-defended against ghost duplicates:
      1. cmd_delete's own pre/post-check (existed before).
      2. Re-list + abort if old source still present (existed before).
      3. _claim_unique_title sweep AFTER successful add (added 2026-04-29
         after observing the eventual-consistency window bypass guards 1+2).
    """
    # Step 1: delete the old source if we have one, then VERIFY it's gone.
    # cmd_delete returns False both for "delete failed" AND "source didn't
    # exist before" — those need different handling here. If the old source
    # is still present after delete, calling cmd_add would create a ghost
    # duplicate (this was the actual mechanism that produced the 9
    # duplicates discovered in cdaa7a43 on 2026-04-26). Abort instead.
    if old_source_id:
        cmd_delete(old_source_id)
        # Settle delay: NotebookLM's source list has a ~1-2s eventual-
        # consistency window after a delete where the deleted source may
        # still appear (or, more dangerously, may temporarily NOT appear
        # before reappearing). Sleep before the post-check to reduce the
        # false-"looks gone" rate. Belt-and-suspenders with the
        # _claim_unique_title sweep below.
        time.sleep(2)
        # Re-check live state regardless of cmd_delete's bool. The CLI exits
        # 0 in too many edge cases for the bool alone to be load-bearing.
        check = run_nb(["source", "list", "--json"])
        if check.returncode == 0:
            try:
                listing = json.loads(check.stdout)
                live = listing if isinstance(listing, list) else listing.get("sources", [])
                still_there = any(
                    (s.get("id") or s.get("source_id") or "").startswith(old_source_id)
                    for s in live
                )
                if still_there:
                    print(f"    ✗ delete didn't take — old source {old_source_id[:12]}… still present, aborting to avoid duplicate")
                    return None, False
            except Exception:
                # If we can't parse the listing we can't be sure either way.
                # Conservative move: don't add. Caller treats this as a
                # failure and won't update state, so we'll retry next run.
                print(f"    ✗ couldn't verify post-delete state, aborting to avoid duplicate")
                return None, False

    # Step 2: add the new file.
    new_sid = cmd_add(path)
    if not new_sid:
        return None, False

    # Step 3: verify content actually indexed.
    verified = cmd_verify_content(new_sid, path)

    # Step 4: ghost-dupe sweep — final safety net for the eventual-consistency
    # case where steps 1's post-check thought the old source was gone but it
    # actually wasn't (or it came back after the add). Without this, we'd
    # leave a stale copy in the notebook for the next preflight to catch.
    ghosts = _claim_unique_title(path.name, new_sid)
    if ghosts > 0:
        print(f"    ! ghost-dupe sweep removed {ghosts} stale copy/copies of {path.name}")

    return new_sid, verified


# ── Routing: bucket wiki files by route ───────────────────────────────────
def plan_routing() -> dict[str, list[Path]]:
    """Walk wiki/*.md; bucket each file into its route by first-match-wins.
    Returns {label: [Path, ...]}. Every route label (plus default) has a key,
    even if the list is empty."""
    buckets: dict[str, list[Path]] = {label: [] for _, _, label, _ in NOTEBOOK_ROUTES}
    default_label = DEFAULT_ROUTE[1]
    buckets[default_label] = []

    for path in iter_wiki_files():
        rel = path.relative_to(VAULT).as_posix()
        # Exclusion check runs before routing: excluded files go to no bucket.
        if is_excluded(rel):
            continue
        matched = False
        for prefix, _nbid, label, _display in NOTEBOOK_ROUTES:
            # Match if path == prefix (file route), is under prefix/ (dir route),
            # or starts with prefix when prefix doesn't end in '/' or '.md' (filename-prefix route,
            # e.g., "wiki/synthesis/hub-" matches "wiki/synthesis/hub-whitepaper.md").
            if rel == prefix:
                buckets[label].append(path)
                matched = True
                break
            if prefix.endswith("/") and rel.startswith(prefix):
                buckets[label].append(path)
                matched = True
                break
            if not prefix.endswith(".md") and not prefix.endswith("/") and rel.startswith(prefix):
                buckets[label].append(path)
                matched = True
                break
        if not matched:
            buckets[default_label].append(path)
    return buckets


# ── Per-route seed/sync ──────────────────────────────────────────────────
def seed_route(notebook_id: str, label: str, display: str, files: list[Path], dry_run: bool) -> None:
    """Match the files routed here to existing notebook sources by filename. Write state file."""
    state_path = state_file_for(label)
    print(f"[{display}] seeding (notebook {notebook_id[:8]}, {len(files)} routed files)...")
    activate_notebook(notebook_id)
    listing = run_nb(["source", "list", "--json"])
    title_to_id = parse_source_list(listing.stdout)
    print(f"  found {len(title_to_id)} existing sources in notebook")

    state = {}
    matched = 0
    unmatched = []
    for path in files:
        title = path.name  # NotebookLM uses filename as title for text sources
        rel = path.relative_to(VAULT).as_posix()
        if title in title_to_id:
            state[rel] = {"mtime": path.stat().st_mtime, "source_id": title_to_id[title]}
            matched += 1
        else:
            unmatched.append(rel)

    print(f"  matched {matched}/{len(files)} routed files to notebook sources")
    if unmatched:
        print(f"  {len(unmatched)} routed files have no match in the notebook:")
        for u in unmatched[:10]:
            print(f"    - {u}")
        if len(unmatched) > 10:
            print(f"    ... and {len(unmatched) - 10} more")

    if not dry_run:
        save_state(state_path, state)
        print(f"  wrote {state_path.name}")


def sync_route(notebook_id: str, label: str, display: str, files: list[Path], dry_run: bool, force: bool = False) -> None:
    """Refresh/add/delete sources in `notebook_id` against the routed `files`."""
    state_path = state_file_for(label)
    state = load_state(state_path)
    # Bail only if state file genuinely doesn't exist — empty state {} is
    # valid (fresh seed against an empty notebook). The original check
    # `if not state and files` falsely treated empty state as missing,
    # which broke the freshly-init'd-project flow on 2026-04-29.
    if not state_path.exists() and files:
        print(f"[{display}] ERROR: no state file ({state_path.name}). Run with --seed first.",
              file=sys.stderr)
        return

    activate_notebook(notebook_id)
    current_files = {p.relative_to(VAULT).as_posix(): p for p in files}
    new_state = dict(state)

    added = refreshed = deleted = unchanged = 0
    verify_failed = upload_failed = 0

    # Files on disk + routed here
    for rel, path in current_files.items():
        mtime = path.stat().st_mtime
        entry = state.get(rel)
        # --force bypasses the mtime-equality shortcut: every tracked file is
        # treated as changed and re-uploaded + verified. Use this after a
        # script bug fix (like the 2026-04-24 cmd_refresh no-op discovery)
        # to force the notebooks to reflect current file contents.
        if entry and entry["mtime"] == mtime and not force:
            unchanged += 1
            continue
        if entry:
            # Changed file: replace (delete old + add new + verify content).
            # Historically this called cmd_refresh() which is a NO-OP for file
            # sources — see cmd_refresh() docstring and wiki/log.md 2026-04-24.
            print(f"  [{display}] ~ replace {rel}")
            if not dry_run:
                sid, verified = cmd_replace(path, entry["source_id"])
                now_ts = time.time()
                if sid and verified:
                    new_state[rel] = {
                        "mtime": mtime, "source_id": sid,
                        "verified_at": now_ts,
                    }
                    refreshed += 1
                    print(f"    ✓ content verified in notebook")
                elif sid and not verified:
                    # Upload succeeded but content check failed. Record the
                    # source_id + leave verified_at absent so the preflight
                    # flags this source as needing re-verification.
                    new_state[rel] = {
                        "mtime": mtime, "source_id": sid,
                    }
                    verify_failed += 1
                    print(f"    ⚠ uploaded but CONTENT NOT VERIFIED — check notebook manually")
                else:
                    upload_failed += 1
                    print(f"    ✗ REPLACE FAILED — {rel} is no longer in the notebook")
            else:
                refreshed += 1
        else:
            # New file (or newly routed here): add + verify
            print(f"  [{display}] + add {rel}")
            if not dry_run:
                sid = cmd_add(path)
                if sid:
                    verified = cmd_verify_content(sid, path)
                    # Ghost-dupe sweep: defends against a previous failed
                    # refresh having left an orphan source for this filename.
                    ghosts = _claim_unique_title(path.name, sid)
                    if ghosts > 0:
                        print(f"    ! ghost-dupe sweep removed {ghosts} stale copy/copies of {rel}")
                    now_ts = time.time()
                    entry_new = {"mtime": mtime, "source_id": sid}
                    if verified:
                        entry_new["verified_at"] = now_ts
                        new_state[rel] = entry_new
                        added += 1
                        print(f"    ✓ content verified in notebook")
                    else:
                        new_state[rel] = entry_new
                        verify_failed += 1
                        print(f"    ⚠ uploaded but CONTENT NOT VERIFIED")
                else:
                    upload_failed += 1
                    print(f"    ✗ ADD FAILED for {rel}")
            else:
                added += 1

    # Files that were in state but no longer on disk (or no longer routed here)
    for rel in list(state.keys()):
        if rel not in current_files:
            print(f"  [{display}] - delete {rel}")
            if not dry_run:
                if cmd_delete(state[rel]["source_id"]):
                    del new_state[rel]
                    deleted += 1
            else:
                deleted += 1

    if not dry_run:
        save_state(state_path, new_state)
    summary = (f"[{display}] DONE  added: {added}  refreshed: {refreshed}  "
               f"deleted: {deleted}  unchanged: {unchanged}  "
               f"verify_failed: {verify_failed}  upload_failed: {upload_failed}  "
               f"dry_run: {dry_run}")
    print(summary)

    # Report this route's sync to /api/agent-activity. Best-effort, skipped on
    # dry-run (only meaningful runs become rows). One row per route so the
    # feed reads as "firehazmat refreshed", "wiki bucket refreshed", etc.
    if not dry_run and (added or refreshed or deleted or verify_failed or upload_failed):
        try:
            helper = Path(__file__).resolve().parent / "report-activity.sh"
            if helper.exists():
                title = (f"notebooklm {display} — "
                         f"{added} added · {refreshed} refreshed · {deleted} deleted"
                         + (f" · {verify_failed} verify_failed" if verify_failed else "")
                         + (f" · {upload_failed} upload_failed" if upload_failed else ""))
                payload = json.dumps({
                    "route":         label,
                    "notebook_id":   notebook_id,
                    "added":         added, "refreshed": refreshed, "deleted": deleted,
                    "unchanged":     unchanged,
                    "verify_failed": verify_failed, "upload_failed": upload_failed,
                    "force":         force,
                })
                subprocess.run(
                    [str(helper),
                     "--source",     "agent",
                     "--event-type", "notebooklm_refresh",
                     "--actor",      "notebooklm-refresh",
                     "--repo",       "openscaffold-wiki",
                     "--title",      title,
                     "--payload",    payload],
                    check=False, timeout=10,
                )
        except Exception:
            pass  # logging is best-effort


# ── Reminder notebook helpers ────────────────────────────────────────────
def iter_reminder_files():
    for rel in REMINDER_FILES:
        p = VAULT / rel
        if p.exists():
            yield p


def load_reminder_state() -> dict:
    if REMINDER_STATE_FILE.exists():
        try:
            return json.loads(REMINDER_STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_reminder_state(state: dict) -> None:
    REMINDER_STATE_FILE.write_text(json.dumps(state, indent=2))


def seed_reminder(dry_run: bool) -> None:
    """Match the curated REMINDER_FILES to ab4b7ccb sources by filename. Write initial state."""
    print(f"[reminder] seeding notebook {REMINDER_NOTEBOOK_ID}...")
    activate_notebook(REMINDER_NOTEBOOK_ID)
    listing = run_nb(["source", "list", "--json"])
    title_to_id = parse_source_list(listing.stdout)
    print(f"  found {len(title_to_id)} existing sources in reminder notebook")

    state = {}
    matched = 0
    unmatched = []
    for path in iter_reminder_files():
        rel = path.relative_to(VAULT).as_posix()
        title = reminder_title_for(rel, path.name)
        if title in title_to_id:
            state[rel] = {"mtime": path.stat().st_mtime, "source_id": title_to_id[title]}
            matched += 1
        else:
            unmatched.append(f"{rel} (looked for title: {title})")

    print(f"  matched {matched}/{len(REMINDER_FILES)} curated files to notebook sources")
    if unmatched:
        print(f"  WARNING: {len(unmatched)} curated file(s) have no match in {REMINDER_NOTEBOOK_ID}:")
        for u in unmatched:
            print(f"    - {u}")
        print(f"  Add them manually with `notebooklm source add <path>` then re-seed,")
        print(f"  or let the next sync auto-add them.")

    if not dry_run:
        save_reminder_state(state)
        print(f"  wrote {REMINDER_STATE_FILE.name}")


def sync_reminder(dry_run: bool, force: bool = False) -> None:
    """Refresh changed files in ab4b7ccb. Add any allowlisted files missing from notebook. Never delete."""
    state = load_reminder_state()
    # Bail only if state file genuinely doesn't exist — empty {} state is
    # valid for a fresh seed against an empty reminder notebook.
    if not REMINDER_STATE_FILE.exists():
        print(f"\n[reminder] no state file — run with --seed first to map source IDs.",
              file=sys.stderr)
        return

    activate_notebook(REMINDER_NOTEBOOK_ID)
    new_state = dict(state)
    refreshed = added = unchanged = missing_on_disk = 0
    verify_failed = upload_failed = 0

    for path in iter_reminder_files():
        rel = path.relative_to(VAULT).as_posix()
        mtime = path.stat().st_mtime
        entry = state.get(rel)
        if entry and entry["mtime"] == mtime and not force:
            unchanged += 1
            continue
        if entry:
            # Replace: delete old + add new + verify. See cmd_refresh docstring.
            print(f"  [reminder] ~ replace {rel}")
            if not dry_run:
                sid, verified = cmd_replace(path, entry["source_id"])
                now_ts = time.time()
                if sid and verified:
                    new_state[rel] = {
                        "mtime": mtime, "source_id": sid,
                        "verified_at": now_ts,
                    }
                    refreshed += 1
                    print(f"    ✓ content verified in notebook")
                elif sid and not verified:
                    new_state[rel] = {"mtime": mtime, "source_id": sid}
                    verify_failed += 1
                    print(f"    ⚠ uploaded but CONTENT NOT VERIFIED — check notebook manually")
                else:
                    upload_failed += 1
                    print(f"    ✗ REPLACE FAILED — {rel} is no longer in the notebook")
            else:
                refreshed += 1
        else:
            print(f"  [reminder] + add {rel}")
            if not dry_run:
                sid = cmd_add(path)
                if sid:
                    verified = cmd_verify_content(sid, path)
                    # Ghost-dupe sweep — same as sync_route's new-file branch.
                    # Uses path.name because cmd_add titles uploads by filename.
                    # REMINDER_TITLE_ALIASES is only relevant for seed matching
                    # of pre-existing manually-renamed sources; new uploads
                    # don't pick up the alias.
                    ghosts = _claim_unique_title(path.name, sid)
                    if ghosts > 0:
                        print(f"    ! ghost-dupe sweep removed {ghosts} stale copy/copies of {rel}")
                    now_ts = time.time()
                    entry_new = {"mtime": mtime, "source_id": sid}
                    if verified:
                        entry_new["verified_at"] = now_ts
                        new_state[rel] = entry_new
                        added += 1
                        print(f"    ✓ content verified in notebook")
                    else:
                        new_state[rel] = entry_new
                        verify_failed += 1
                        print(f"    ⚠ uploaded but CONTENT NOT VERIFIED")
                else:
                    upload_failed += 1
                    print(f"    ✗ ADD FAILED for {rel}")
            else:
                added += 1

    # Note any allowlisted files that no longer exist on disk (not auto-deleted)
    for rel in REMINDER_FILES:
        if not (VAULT / rel).exists():
            print(f"  ! {rel} listed in REMINDER_FILES but not found on disk (notebook source NOT removed)")
            missing_on_disk += 1

    if not dry_run:
        save_reminder_state(new_state)
    summary = (f"[reminder] DONE  added: {added}  refreshed: {refreshed}  "
               f"unchanged: {unchanged}  missing_on_disk: {missing_on_disk}  "
               f"verify_failed: {verify_failed}  upload_failed: {upload_failed}  "
               f"dry_run: {dry_run}")
    print(summary)

    # Same activity-report pattern as sync_route, scoped to the reminder bucket.
    if not dry_run and (added or refreshed or verify_failed or upload_failed):
        try:
            helper = Path(__file__).resolve().parent / "report-activity.sh"
            if helper.exists():
                title = (f"notebooklm reminder bucket — "
                         f"{added} added · {refreshed} refreshed"
                         + (f" · {verify_failed} verify_failed" if verify_failed else "")
                         + (f" · {upload_failed} upload_failed" if upload_failed else ""))
                payload = json.dumps({
                    "route":           "reminder",
                    "notebook_id":     REMINDER_NOTEBOOK_ID,
                    "added":           added, "refreshed": refreshed,
                    "unchanged":       unchanged, "missing_on_disk": missing_on_disk,
                    "verify_failed":   verify_failed, "upload_failed": upload_failed,
                    "force":           force,
                })
                subprocess.run(
                    [str(helper),
                     "--source",     "agent",
                     "--event-type", "notebooklm_refresh",
                     "--actor",      "notebooklm-refresh",
                     "--repo",       "openscaffold-wiki",
                     "--title",      title,
                     "--payload",    payload],
                    check=False, timeout=10,
                )
        except Exception:
            pass


# ── Notebook coverage check ──────────────────────────────────────────────
# Compares NotebookLM's actual notebook list against the script's known set
# (NOTEBOOK_ROUTES + DEFAULT_ROUTE + REMINDER_NOTEBOOK_ID + IGNORED_NOTEBOOKS)
# and reports orphans. Called by the preflight via `--check-coverage`. Closes
# the gap that let TheMatch (e9337dea) sit unrouted for weeks (2026-04-29).
def check_coverage() -> int:
    """Print orphan notebooks, one per line as 'ID<TAB>title'.
    Returns: 0 if no orphans, N>0 if N orphans, -1 on tool failure."""
    listing = run_nb(["list", "--json"])
    if listing.returncode != 0:
        print(f"notebooklm list failed: {listing.stderr}", file=sys.stderr)
        return -1
    try:
        data = json.loads(listing.stdout)
    except Exception as e:
        print(f"notebooklm list JSON parse failed: {e}", file=sys.stderr)
        return -1
    notebooks = data.get("notebooks", []) if isinstance(data, dict) else data

    # Build the "known" set: routed + default + reminder + ignored.
    known: set[str] = set()
    for _prefix, nbid, _label, _display in NOTEBOOK_ROUTES:
        known.add(nbid)
    known.add(DEFAULT_ROUTE[0])
    # Reminder ID is stored in short form (ab4b7ccb) historically; we accept
    # both short and full UUID forms via prefix matching below.
    known.add(REMINDER_NOTEBOOK_ID)
    known.update(IGNORED_NOTEBOOKS.keys())

    def _is_known(nid: str) -> bool:
        # Match exact OR prefix (so a short-form known ID matches a full UUID)
        return any(nid == k or nid.startswith(k) for k in known)

    orphans = []
    for nb in notebooks:
        nid = nb.get("id")
        title = (nb.get("title") or "(untitled)").strip()
        if nid and not _is_known(nid):
            orphans.append((nid, title))

    for nid, title in orphans:
        # Tab-separated so the bash preflight can parse with IFS=$'\t'
        print(f"{nid}\t{title}")
    return len(orphans)


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Keep OpenScaffold NotebookLM notebooks in sync with the vault.",
    )
    parser.add_argument("--seed", action="store_true",
                        help="first-time / post-migration: match existing notebook sources to files by title (writes all selected state files)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="treat every tracked file as changed. Use after a sync-mechanism "
                             "bug fix to force re-upload + content-verify across all sources.")
    parser.add_argument("--verify-existing", action="store_true",
                        help="run cmd_verify_content against every entry currently in state, "
                             "writing verified_at timestamps on success. No uploads. Use this "
                             "after a verify-function improvement to backfill verified_at "
                             "without paying for another full delete+re-add sync.")
    parser.add_argument("--skip-auth-check", action="store_true")
    parser.add_argument("--check-coverage", action="store_true",
                        help="compare NotebookLM's notebooks against routing + IGNORED_NOTEBOOKS. "
                             "Print orphans (one per line, ID<TAB>title) and exit. "
                             "Exit 0 if all known, 1 if N orphans, 2 on tool failure. "
                             "Used by tools/limitless-preflight.sh.")
    only_choices = ["wiki", "reminder", "all-projects"] + PROJECT_LABELS
    parser.add_argument("--only", choices=only_choices,
                        help="run only one route. 'wiki' = default bucket (cdaa7a43) only; "
                             "'all-projects' = every per-project route, skip wiki default and reminder; "
                             "<project> = just that notebook; 'reminder' = ab4b7ccb only. Default: all.")
    args = parser.parse_args()

    if not args.skip_auth_check:
        if not check_auth():
            sys.exit(1)

    # --check-coverage runs before route selection; it has its own exit semantics.
    # 0 = all notebooks routed/ignored, 1 = orphans found, 2 = tool failure.
    if args.check_coverage:
        n = check_coverage()
        if n < 0:
            sys.exit(2)
        sys.exit(0 if n == 0 else 1)

    # Decide which route labels (project + default) to run, and whether reminder runs
    if args.only is None:
        labels_to_run = PROJECT_LABELS + [DEFAULT_ROUTE[1]]
        do_reminder = True
    elif args.only == "all-projects":
        labels_to_run = list(PROJECT_LABELS)
        do_reminder = False
    elif args.only == "reminder":
        labels_to_run = []
        do_reminder = True
    elif args.only == "wiki":
        labels_to_run = [DEFAULT_ROUTE[1]]
        do_reminder = False
    else:  # a specific project label
        labels_to_run = [args.only]
        do_reminder = False

    if args.verify_existing:
        # Standalone verify pass: no uploads, just checks every tracked source
        # against its local file and writes verified_at timestamps on success.
        run_verify_existing(labels_to_run, do_reminder, args.dry_run)
        return

    if labels_to_run:
        buckets = plan_routing()
        for label in labels_to_run:
            nbid, _, display = route_for_label(label)
            files = buckets.get(label, [])
            if args.seed:
                seed_route(nbid, label, display, files, args.dry_run)
            else:
                sync_route(nbid, label, display, files, args.dry_run, force=args.force)

    if do_reminder:
        if args.seed:
            seed_reminder(args.dry_run)
        else:
            sync_reminder(args.dry_run, force=args.force)


def run_verify_existing(labels_to_run: list, do_reminder: bool, dry_run: bool) -> None:
    """Check every tracked source's content matches its local file. Write
    verified_at timestamps on success. No uploads. Intended for backfilling
    verified_at after a verify-function improvement, and for auditing drift.
    """
    def _verify_batch(state_path: Path, notebook_id: str, display: str) -> None:
        state = load_state(state_path)
        if not state:
            print(f"[{display}] no state file; skip")
            return
        activate_notebook(notebook_id)
        new_state = dict(state)
        checked = verified = stale = missing_disk = 0
        for rel, entry in state.items():
            path = VAULT / rel
            if not path.exists():
                print(f"  [{display}] ? {rel} not on disk; skip")
                missing_disk += 1
                continue
            checked += 1
            ok = cmd_verify_content(entry["source_id"], path, wait_retries=2)
            if ok:
                new_entry = dict(entry)
                new_entry["verified_at"] = time.time()
                new_state[rel] = new_entry
                verified += 1
                print(f"  [{display}] ✓ {rel}")
            else:
                stale += 1
                print(f"  [{display}] ✗ {rel}  (content check failed — source is stale)")
        if not dry_run:
            save_state(state_path, new_state)
        print(f"[{display}] VERIFY DONE  checked: {checked}  verified: {verified}  "
              f"stale: {stale}  missing_on_disk: {missing_disk}")

    for label in labels_to_run:
        nbid, _, display = route_for_label(label)
        _verify_batch(state_file_for(label), nbid, display)

    if do_reminder:
        _verify_batch(REMINDER_STATE_FILE, REMINDER_NOTEBOOK_ID, "reminder")


if __name__ == "__main__":
    main()
