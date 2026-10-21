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
import hashlib
import notebooklm_sync_safety as _SAFETY
import notebooklm_log_exports as _LOG_EXPORTS
import json
import os
import re
import shutil
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

# One entry per LABEL, not per route. Several path prefixes legitimately map to
# the same notebook (openfirehouse has 10, hub has 8), but plan_routing() returns
# the COMPLETE file list for a label, so a label needs exactly one pass. Without
# this dedupe a default run re-processed openfirehouse's whole bucket 10 times and
# hub's 8 times — 18 redundant passes, each re-listing the notebook and opening
# another delete-then-add window, and each printing a duplicate preflight line
# (the repeated "mirror in sync" lines that made the Roll Call output unreadable).
# dict.fromkeys preserves first-seen order. Fixed 2026-08-03.
PROJECT_LABELS = list(dict.fromkeys(r[2] for r in NOTEBOOK_ROUTES))

# ── Exclusion list ────────────────────────────────────────────────────────
# Files matching any of these prefixes are not mirrored to any ROUTED notebook —
# not a per-project notebook and not the default cdaa7a43 bucket.
#
# ⚠ CORRECTED 2026-08-24: this comment used to say "not the reminder" as well.
# That was never true. is_excluded() is consulted ONLY by route_files(); the
# curated REMINDER_FILES allowlist is iterated separately and never calls it.
# A reminder-allowlisted page therefore stays in ab4b7ccb even if it appears
# here. Do NOT "fix" the code to match the old comment — the reminder bucket is
# what the next session reads first, and emptying it would be silent. To drop a
# page from the general bucket while keeping it in the reminder, use
# EXCLUDE_FROM_DEFAULT_BUCKET below, which states that intent explicitly.
#
# These are wiki summary pages whose underlying source material
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
    # Pruned from cdaa7a43 on 2026-07-13, same reason: the 50-source cap was full and
    # two NEW handoffs (accountability + prevention-offline) could not be added. A session
    # handoff's purpose EXPIRES the moment the next session starts — these three are a
    # month old and are superseded by wiki/apps/openfirehouse.md + wiki/log.md. The files
    # stay on disk and in git (backlinks intact); they just stop occupying NotebookLM slots.
    # NOTE: handoffs-rollup.md in that notebook is from the the-match vault and does NOT
    # cover these — checked before pruning, so this is a deliberate drop, not a rollup.
    "wiki/synthesis/session-handoff-2026-06-13.md",
    "wiki/synthesis/session-handoff-2026-06-14.md",
    "wiki/synthesis/session-handoff-2026-06-15.md",
    # CONSOLIDATED 2026-09-11 into wiki/synthesis/stack-handoffs-rollup.md, which
    # takes their place in cdaa7a43 (47 sources -> 40, against the 50-source cap).
    # These eight matched no project prefix, so each held its own slot in the general
    # bucket. Unlike the 05-03 and 07-13 prunes above this is NOT a drop: every byte
    # is in the rollup, verbatim, newest-first. Files stay on disk and in git as the
    # primary read path. Regenerate with tools/notebooklm-rollup.py.
    "wiki/synthesis/handoff-2026-08-27-log-order-and-memory-fixes.md",
    "wiki/synthesis/handoff-2026-08-25-whichtree-and-three-retractions.md",
    "wiki/synthesis/handoff-2026-08-24-night-audit-and-cleanup.md",
    "wiki/deliverables/HANDOFF-2026-08-24-TASK-RELIABILITY-AND-SHELL-SAFETY.md",
    "wiki/synthesis/session-handoff-2026-08-20-hub-chat.md",
    "wiki/synthesis/session-handoff-2026-08-04.md",
    "wiki/synthesis/session-handoff-2026-08-03-neris-picker.md",
    "wiki/synthesis/handoff-notice-templates-2026-08-03.md",
]

# ── Excluded from the DEFAULT bucket only (added 2026-08-24) ─────────────────
# Weaker than EXCLUDE_FROM_NOTEBOOKS: a page listed here is dropped from the
# general cdaa7a43 bucket but keeps every OTHER home it has — in practice, the
# curated ab4b7ccb reminder allowlist, which CLAUDE.md tells each session to
# query first. A page that is complete in the reminder does not need a second
# slot in the general bucket.
# ⚠ Per-project routes are unaffected: this is applied at the default fallback
# only, so a page that matches a NOTEBOOK_ROUTES prefix never reaches it.
# Overridable per project via the manifest's NOTEBOOKLM["exclude_from_default"].
EXCLUDE_FROM_DEFAULT_BUCKET: list[str] = []


def is_excluded(rel_path: str) -> bool:
    """True if `rel_path` matches any EXCLUDE_FROM_NOTEBOOKS prefix."""
    return any(rel_path.startswith(prefix) for prefix in EXCLUDE_FROM_NOTEBOOKS)


def state_file_for(label: str) -> Path:
    """Return <STATE_DIR>/.notebooklm-<label>-state.json for a given route label
    (tools/ for the owner; members/<login>/notebooklm-state/ for a teammate)."""
    return STATE_DIR / f".notebooklm-{label}-state.json"


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

# ── Per-person notebooks in a shared vault (2026-09-24) ──────────────────
# The manifest names the vault OWNER's notebooks. A teammate works against their
# OWN notebooks, declared in members/<login>/notebooklm.py, with their upload
# records in members/<login>/notebooklm-state/. tools/limitless_member.py does the
# swap; for the owner (or a personal vault) it returns the block unchanged and
# STATE_DIR stays tools/, so nothing about the owner's setup moves.
STATE_DIR = TOOLS
ROUTING_ORDER = None          # teammate only: every vault route, None label = not carried
MEMBER = {"login": "", "role": "owner"}
try:
    import limitless_member as _lm
    _NB_MANIFEST, STATE_DIR, MEMBER = _lm.apply(VAULT, _NB_MANIFEST, _MANIFEST.get("VAULT_OWNER", "") or "")
except ImportError:
    pass
except ValueError as _e:
    print(f"ERROR: {_e}", file=sys.stderr)
    sys.exit(2)

if "routes" in _NB_MANIFEST:
    NOTEBOOK_ROUTES = _NB_MANIFEST["routes"]
    PROJECT_LABELS = list(dict.fromkeys(r[2] for r in NOTEBOOK_ROUTES))  # see the module-level note
if "default" in _NB_MANIFEST:
    DEFAULT_ROUTE = _NB_MANIFEST["default"]
if "ignored" in _NB_MANIFEST:
    IGNORED_NOTEBOOKS = _NB_MANIFEST["ignored"]
if "exclude_paths" in _NB_MANIFEST:
    EXCLUDE_FROM_NOTEBOOKS = _NB_MANIFEST["exclude_paths"]
if "exclude_from_default" in _NB_MANIFEST:
    EXCLUDE_FROM_DEFAULT_BUCKET = _NB_MANIFEST["exclude_from_default"]
_REMINDER = _NB_MANIFEST.get("reminder", {})
if "notebook_id" in _REMINDER:
    REMINDER_NOTEBOOK_ID = _REMINDER["notebook_id"]
if "files" in _REMINDER:
    REMINDER_FILES = _REMINDER["files"]
if "title_aliases" in _REMINDER:
    REMINDER_TITLE_ALIASES = _REMINDER["title_aliases"]


try:
    import notebooklm_external as _EXTERNAL   # sources outside the vault (2026-09-25)
except ImportError:
    _EXTERNAL = None

if "routing_order" in _NB_MANIFEST:
    ROUTING_ORDER = _NB_MANIFEST["routing_order"]
REMINDER_STATE_FILE = STATE_DIR / ".notebooklm-reminder-state.json"


def reminder_title_for(rel_path: str, basename: str) -> str:
    """Title to look up (or use when adding) in ab4b7ccb."""
    return REMINDER_TITLE_ALIASES.get(rel_path, basename)


# ── notebooklm-py CLI wrappers ───────────────────────────────────────────
# The notebook every `source *` call is pinned to. `notebooklm use` writes a
# SINGLE SHARED context file, so any concurrent process — the preflight's
# 8-notebook dedupe sweep, the nightly self-heal, a second session — can
# repoint it between our `use` and our next command. This tool ADDS and
# DELETES sources, so a lost race here does not read the wrong notebook, it
# WRITES to it. Verified live 2026-08-03: a background preflight moved the
# context mid-run and a dedupe pass enumerated the wrong bucket. Every
# `source` subcommand (add/delete/refresh/fulltext/list) accepts --notebook —
# confirmed against CLI 0.8.0 — so pinning costs nothing.
_ACTIVE_NOTEBOOK: str | None = None

# Subcommands that are notebook-scoped. Anything else (auth, list, profile)
# must NOT receive --notebook.
_NB_SCOPED = {"source", "ask", "artifact", "note", "generate", "download", "research"}


def run_nb(args: list[str]) -> subprocess.CompletedProcess:
    """Run a notebooklm-py CLI command, pinned to the active notebook.

    Injects `--notebook <id>` for notebook-scoped subcommands unless the
    caller already passed one explicitly (a few call sites target a specific
    notebook directly and must win over the global).
    """
    argv = list(args)
    if (_ACTIVE_NOTEBOOK and argv and argv[0] in _NB_SCOPED
            and "--notebook" not in argv and "-n" not in argv):
        argv += ["--notebook", _ACTIVE_NOTEBOOK]
    return subprocess.run(
        ["notebooklm"] + argv,
        capture_output=True, text=True,
    )


def activate_notebook(nbid: str) -> None:
    """Pin every source call without changing the CLI's shared context file."""
    global _ACTIVE_NOTEBOOK
    _ACTIVE_NOTEBOOK = nbid


def check_auth() -> bool:
    result = subprocess.run(["notebooklm", "auth", "check", "--test", "--passive", "--json"], capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = {}
    ok = result.returncode == 0 and data.get("status") == "ok" and data.get("checks", {}).get("token_fetch") is True
    if not ok:
        print("NotebookLM authentication did not pass a real token check; no source changes made", file=sys.stderr)
    return ok


# ── State file helpers (per-route) ───────────────────────────────────────
def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        state = json.loads(state_path.read_text())
        if not isinstance(state, dict):
            raise ValueError("state must be an object")
        return state
    except (ValueError, OSError) as exc:
        raise SyncVerificationError(f"Cannot read {state_path}; refusing to discard its receipts") from exc


def save_state(state_path: Path, state: dict) -> None:
    _SAFETY.save_json(state_path, state)
    _SAFETY.finish_receipts(STATE_DIR)


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


class SyncVerificationError(RuntimeError):
    """A sync failed; existing sources and verified receipts must be retained."""


def _processing_error_detail(source_id: str) -> str:
    """Read the error metadata omitted by the CLI; never return source text."""
    import asyncio
    from notebooklm import NotebookLMClient
    from notebooklm.rpc import RPCMethod

    async def read():
        async with NotebookLMClient.from_storage() as client:
            result = await client.rpc_call(
                RPCMethod.GET_SOURCE, [[source_id], [2], [2]],
                allow_null=True, raise_on_null_status=True,
            )
            return result[0][3]

    try:
        block = asyncio.run(read())
        return "processing metadata=" + json.dumps(block)
    except Exception as exc:
        return "processing metadata unavailable (" + type(exc).__name__ + ")"


def _require_ready(source_id: str) -> None:
    result = run_nb(["source", "wait", source_id, "--timeout", "120", "--json"])
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        data = {}
    if result.returncode != 0 or data.get("status") != "ready":
        reason = _processing_error_detail(source_id)
        raise SyncVerificationError(
            f"Source {source_id} is not READY (wait exit={result.returncode}, "
            f"status={data.get('status', 'unknown')}); {reason}. "
            "No prior source retired; no automatic re-upload."
        )


def cmd_add(path: Path) -> str | None:
    """Add a file, return source_id or None."""
    if not path.is_file():
        raise SyncVerificationError(f"Upload input is not a file: {path}")
    result = run_nb(["source", "add", str(path), "--type", "file", "--request-timeout", "90", "--json"])
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        data = {}
    sid = (data.get("source") or {}).get("id")
    if result.returncode != 0 or not sid:
        raise SyncVerificationError(
            f"Upload registration failed for {path.name} (exit={result.returncode}, "
            f"candidate={sid or 'unknown'}); old source/receipt retained. "
            "Do not retry an uncertain registration blindly."
        )
    return sid


def cmd_refresh(source_id: str) -> bool:
    """⚠ NO-OP FOR FILE SOURCES. Kept for URL/Drive source compatibility only.

    Per the CLI help: `refresh  Refresh a URL/Drive source.` — for file-based
    (markdown/text) sources this silently succeeds with returncode=0 but does
    NOT replace the indexed content. Historically we trusted this and spent
    weeks with stale content in notebooks (see wiki/log.md 2026-04-24 entry).

    For file sources, use cmd_replace() instead — it does add + verify + retire +
    content verification.
    """
    result = run_nb(["source", "refresh", source_id])
    return result.returncode == 0


def source_present(source_id: str) -> bool:
    """Is `source_id` in the ACTIVE notebook right now?

    Deliberately fails CLOSED — returns True when the listing can't be read or
    parsed. Callers use this to decide whether a state entry is stale enough to
    delete, and "I couldn't tell" must never be enough to discard bookkeeping for
    a source that may well be live.
    """
    r = run_nb(["source", "list", "--json"])
    if r.returncode != 0:
        return True
    try:
        data = json.loads(r.stdout)
        sources = data if isinstance(data, list) else data.get("sources", [])
    except Exception:
        return True
    return any(
        (s.get("id") or s.get("source_id") or "").startswith(source_id)
        for s in sources
    )


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
      - backticks (code spans) — each becomes a word break, not nothing
      - markdown link brackets [text] and (url)
      - heading hash prefixes (#, ##, ###)
      - wiki-link double brackets [[target]] → target
      - emphasis markers (*, _, **)
      - list bullets ("- ", "+ ") at the start of a line
      - collapses whitespace
    Apply the same transformations before comparing so our verify check
    doesn't throw false negatives on markdown formatting differences.

    List bullets added 2026-10-10: the indexed text has no "- " where a list
    item starts ("…CI green) - Matt greenlit…" locally is "…CI green) Matt
    greenlit…" in the notebook), so a 30-char marker that straddled a bullet
    missed although every word of it was there. That alone made all 6 of the
    6 "stale" verdicts in that day's --only wiki --verify-existing run (log.md,
    index.md, llm-wiki-pattern.md, openscaffold-core.md, matt.md, dale.md):
    hits 1-2/5 before, 3-5/5 with bullets stripped; overview.md (passing)
    stayed 5/5; markers against a DIFFERENT file's text stayed 0-1/5. The
    threshold and the marker count are unchanged.

    Code spans, the same day: the index keeps a word break where a backtick
    was ("`a`, `b`" reads "a , b" there), so deleting the backtick joined what
    the notebook keeps apart. With bullets alone, self-heal-pipeline.md fell
    from 3/5 to 2/5 when its markers shifted onto two code spans. Both fixes,
    measured on all 40 sources of the wiki route: 35 passed before, 40 after
    (none at 3/5 or below); each file's markers against the next file's text
    reached at most 1/5, before and after.
    """
    # Strip common markdown punctuation that NotebookLM normalizes away
    s = re.sub(r"^[ \t]*[-+][ \t]+", "", s, flags=re.MULTILINE)  # list bullets (first: as measured)
    s = s.replace("`", " ")              # code spans: a backtick leaves a word break in the index
    s = re.sub(r"[*_]", "", s)           # bold, italic
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
        # notebooklm-py 0.7.3 (installed 2026-07-31 16:26) BROKE the "-o writes
        # pure content" contract this function's docstring relies on: it now
        # emits a long rule of dashes before the body. Nothing here recognised
        # it, so the rule and everything framed by it stayed in the "content".
        # This is the SAME class as f67ce20 (2026-07-11), which taught check_caps
        # about a 'Matched:' preamble — the CLI keeps changing its output shape
        # and we keep parsing it by hardcoded prefix. Matching a dash-rule by
        # shape rather than by exact string so the next variant does not break us.
        or (len(ln.strip()) >= 8 and set(ln.strip()) <= {"-", "=", "_"})
    )]
    return "\n".join(keep)


def _prose_lines(text: str) -> str:
    """Return only the prose lines of a markdown file — dropping YAML
    frontmatter, fenced code blocks, and markdown table rows/separators.

    cmd_verify_content samples short markers from this text. NotebookLM's
    indexer REFLOWS tables (strips the pipe delimiters, drops separator
    rows, and reorders cell text) and can rewrite fenced code, so a marker
    that lands inside those regions won't appear verbatim in the indexed
    copy even when the upload succeeded — producing a false "stale" verdict.
    Prose (paragraphs, headings, list text) indexes verbatim, so sampling
    markers from it gives a trustworthy signal. Headings are kept (their
    leading '#' is normalized away later by _strip_for_compare).

    Conservative on purpose: only lines that START with a pipe, or are made
    up solely of table-separator characters, are treated as table lines, so
    ordinary prose that happens to contain a pipe is never dropped.
    """
    out = []
    in_frontmatter = False
    in_code = False
    for i, ln in enumerate(text.splitlines()):
        stripped = ln.strip()
        # YAML frontmatter: a '---' fenced block only when it opens line 0.
        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        # Fenced code blocks (``` or ~~~).
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Markdown table rows (leading pipe) and separator rows (only made of
        # pipes / dashes / colons / spaces, e.g. |---|:--:|).
        if stripped.startswith("|"):
            continue
        if stripped and set(stripped) <= set("|-: "):
            continue
        out.append(ln)
    return "\n".join(out)


def cmd_verify_content(source_id: str, path: Path, wait_retries: int = 5) -> bool:
    """Fetch the source's indexed fulltext and confirm it matches the local
    file closely enough. NotebookLM's indexer is LOSSY: it strips markdown
    punctuation (backticks, brackets, heading #'s, emphasis), REFLOWS tables
    (drops pipes/separators, reorders cells), AND drops chunks of content
    (observed ~5% shrinkage on a 17K-char file with code blocks). Any
    exact-match strategy on long strings will false-fail.

    Strategy: pick 5 short (30-char) markers evenly spaced through the
    normalized PROSE of the file (frontmatter, code blocks, and table rows
    excluded — see _prose_lines), and require at least 3 of 5 to appear in
    the remote. Sampling prose rather than the whole file avoids false
    "stale" verdicts on table-heavy pages, where markers landing in reflowed
    tables would miss even though the upload succeeded. Genuine staleness is
    still caught (a truly different remote matches 0–1 markers). When a page
    has too little prose to sample (<150 normalized chars, e.g. an almost
    all-table page), fall back to whole-file markers — no worse than the
    pre-fix behavior for that rare case.

    Polls with backoff to let indexing complete.

    ⚠ BUDGET WIDENED 2026-08-01. The old schedule was [2,4,8,16,30] with
    wait_retries=5 — and because the sleep happens BEFORE each retry, the last
    delay was never reached, so the real budget was 2+4+8+16 = **30 seconds**.
    notebooklm-py was upgraded to 0.7.3 on Jul 31 16:26; the very next refresh
    (17:43) returned verify_failed on 5 of 5 files, and the following one failed
    again. Proven false negatives: the uploads had SUCCEEDED — the same markers
    that failed in-run scored 5/5 when re-checked ~30 min later, the remote
    fulltext contained every new string, and a live query answered from the new
    content. 0.7.3 changed the timing between "upload returns" and "content is
    retrievable"; the old budget was tuned to the previous behaviour.

    Not size-related: the failures spanned 8KB to 259KB. Not a stale source_id
    either: state and notebook ids matched.
    """
    _require_ready(source_id)
    delays = [3, 7, 15, 30, 60, 90, 120]
    local_text = path.read_text()
    prose_norm = _strip_for_compare(_prose_lines(local_text))
    # Prefer prose markers; fall back to whole-file only when prose is too thin.
    local_norm = prose_norm if len(prose_norm) >= 150 else _strip_for_compare(local_text)
    required = []
    if re.fullmatch(r"log-(?:recent|older-\d{3})\.md", path.name):
        required = [local_norm[:80], local_norm[-120:]]
        required += [_strip_for_compare(line) for line in local_text.splitlines() if re.match(r"^## \[\d{4}-", line)][-4:]
        required = [m for m in required if m]
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
        #
        # REVERTED to the original five on 2026-08-01. I had widened this to nine
        # while hunting the "everything is stale" outage, on the theory that the
        # 3-of-5 threshold was too tight. That theory was WRONG — the real cause
        # was the temp-file collision above — and widening it also LOOSENED the
        # bar (5-of-9 = 56% vs 3-of-5 = 60%). Changing the pass criterion while
        # chasing a bug means later "stale" verdicts get judged by a rule altered
        # on a hunch, so it goes back. If sampling is genuinely too brittle, that
        # deserves its own evidence and its own change.
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
        # ── DO NOT PRE-CREATE THE TARGET FILE ────────────────────────────────
        # ROOT CAUSE of the 2026-07-31/08-01 "everything is stale" outage.
        # This used to be tempfile.NamedTemporaryFile(delete=False), which
        # CREATES the file and then handed its path to `-o`. notebooklm-py 0.7.3
        # (installed 2026-07-31 16:26) will NOT overwrite an existing file — it
        # silently auto-renames, writing to "…tmpXXXX (2).txt" instead. So the
        # CLI reported success ("Saved 6985 chars to /tmp/tmpyd2gryml (2).txt",
        # returncode 0) while the tool read its own still-EMPTY temp file, hit
        # the `st_size == 0 → continue` guard, exhausted every retry, and
        # reported "source is stale".
        #
        # It failed on 100% of replaced sources regardless of size (8KB–259KB),
        # with matching source_ids and content that was provably present — a
        # pure false negative. Use a temp DIRECTORY and a path inside it that
        # does not yet exist, so there is nothing for the CLI to collide with.
        tmp_dir = tempfile.mkdtemp(prefix="nblm-verify-")
        tmp_path = str(Path(tmp_dir) / "fulltext.txt")
        try:
            result = run_nb(["source", "fulltext", source_id, "-o", tmp_path])
            if result.returncode != 0:
                continue
            tp = Path(tmp_path)
            # Belt and braces: if the CLI still wrote somewhere else, believe the
            # CLI over our assumption and read the path IT reports. Parsing its
            # stdout is fragile, which is exactly why the empty-file case must
            # never again be silently treated as "stale".
            if not tp.exists() or tp.stat().st_size == 0:
                m = re.search(r"Saved\s+\d+\s+chars?\s+to\s+(.+?)\s*$",
                              result.stdout or "", re.MULTILINE)
                alt = Path(m.group(1)) if m else None
                if alt and alt.exists() and alt.stat().st_size > 0:
                    tp = alt
                else:
                    # Could not READ the source. That is not evidence of staleness.
                    print(f"    ⚠ verify could not read fulltext for {path.name} "
                          f"(rc={result.returncode}, empty output) — treating as UNKNOWN, not stale")
                    continue
            remote_text = _extract_content(tp.read_text())
            remote_norm = _strip_for_compare(remote_text)
            if remote_norm and _check_short(remote_norm) and all(m in remote_norm for m in required):
                return True
        finally:
            # Remove the whole temp DIR (not just the file) — and anything the
            # CLI may have auto-renamed into it, e.g. "fulltext (2).txt".
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return False








def cmd_replace(path: Path, old_source_id: str | None) -> tuple[str | None, bool, bool]:
    """Register once, journal candidate, verify READY/indexed content, then retire prior ID.

    The durable journal is a recovery receipt until the normal state checkpoint.
    A failure retains the prior receipt and never starts an automatic re-upload.
    """
    return _SAFETY.replace(sys.modules[__name__], path, old_source_id)


def heal_verify(path: Path, sid: str | None, attempts: int = 2) -> tuple[str | None, bool, bool]:
    """Compatibility hook: patient read-only verification, never re-upload/delete."""
    return sid, bool(sid) and cmd_verify_content(sid, path, wait_retries=7), False


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
        for prefix, _nbid, label, _display in (ROUTING_ORDER or NOTEBOOK_ROUTES):
            # Match if path == prefix (file route), is under prefix/ (dir route),
            # or starts with prefix when prefix doesn't end in '/' or '.md' (filename-prefix route,
            # e.g., "wiki/synthesis/hub-" matches "wiki/synthesis/hub-whitepaper.md").
            if (rel == prefix
                    or (prefix.endswith("/") and rel.startswith(prefix))
                    or (not prefix.endswith(".md") and not prefix.endswith("/") and rel.startswith(prefix))):
                if label is not None:          # None: a project this person doesn't carry
                    buckets[label].append(path)
                matched = True
                break
        if not matched:
            # Default-bucket-only exclusion. Applied HERE, after every route has
            # had its chance, so it can never affect a per-project notebook.
            if any(rel.startswith(p) for p in EXCLUDE_FROM_DEFAULT_BUCKET):
                continue
            buckets[default_label].append(path)
    exports = log_export_plan()
    if exports:
        source, directory, _metadata, planned = exports
        for label, paths in buckets.items():
            if source in paths:
                index = paths.index(source)
                paths[index:index+1] = [directory / name for name in planned.files]
    return buckets




def log_export_plan():
    cfg = _NB_MANIFEST.get("log_exports")
    if not cfg:
        return None
    source = VAULT / cfg["path"]
    metadata_path = STATE_DIR / ".notebooklm-log-exports.json"
    prior = load_state(metadata_path) if metadata_path.exists() else None
    try:
        planned = _LOG_EXPORTS.plan(source.read_bytes(), prior, cfg.get("max_words", 300000))
    except (OSError, _LOG_EXPORTS.LogExportError) as exc:
        raise SyncVerificationError(f"Log exports were not changed: {exc}") from exc
    return source, STATE_DIR / "notebooklm-exports", metadata_path, planned


def prepare_log_exports(dry_run=False, verify_only=False):
    got = log_export_plan()
    if got is None:
        return
    source, directory, metadata_path, planned = got
    print("[log exports] " + "  ".join(f"{n}: {len(b.decode().split())} words" for n,b in planned.files.items()))
    if verify_only:
        if any(not (directory/n).exists() or (directory/n).read_bytes() != b for n,b in planned.files.items()):
            raise SyncVerificationError("Log exports need regeneration from the current log; run the scoped refresh before verifying")
    elif not dry_run:
        _LOG_EXPORTS.publish(directory, metadata_path, planned)


def _sync_files(notebook_id, display, state_path, files, dry_run, force, prune):
    if not state_path.exists() and files:
        raise SyncVerificationError(f"No state file {state_path}; seed this route first")
    state = load_state(state_path)
    new_state = dict(state)
    activate_notebook(notebook_id)
    current = {p.relative_to(VAULT).as_posix(): p for p in files}
    counts = dict(added=0, refreshed=0, deleted=0, unchanged=0, verify_failed=0, upload_failed=0, stale_dropped=0)
    listing = run_nb(["source", "list", "--json"])
    if listing.returncode:
        raise SyncVerificationError("Cannot list route sources; nothing changed")
    try:
        listing_data = json.loads(listing.stdout)
        live = listing_data if isinstance(listing_data, list) else listing_data["sources"]
        ready_ids = {r.get("id") or r.get("source_id") for r in live if r.get("status") == "ready"}
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncVerificationError("Cannot parse route source status; nothing changed") from exc
    for rel, path in current.items():
        mtime = path.stat().st_mtime if path.exists() else 0
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
        entry = state.get(rel)
        if (entry and entry.get("mtime") == mtime and entry.get("verified_at")
                and entry.get("source_id") in ready_ids
                and entry.get("sha256", digest) == digest and not force):
            counts["unchanged"] += 1
            continue
        action = "refreshed" if entry else "added"
        print(f"  [{display}] ~ {'replace' if entry else 'add'} {rel}")
        if dry_run:
            counts[action] += 1
            continue
        sid, verified, _gone = cmd_replace(path, entry.get("source_id") if entry else None)
        if not sid or not verified:
            raise SyncVerificationError(f"No verified replacement for {rel}; prior receipt retained")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SyncVerificationError(f"{rel} changed during upload; candidate journal retained for reconciliation")
        new_state[rel] = {"mtime": mtime, "sha256": digest, "source_id": sid, "verified_at": time.time()}
        save_state(state_path, new_state)
        counts[action] += 1
    # All current sources have passed verification or match an existing verified,
    # READY receipt. In particular ALL log parts precede retirement of log.md.
    if prune:
        for rel, entry in state.items():
            if rel in current:
                continue
            sid = entry["source_id"]
            print(f"  [{display}] - retire {rel} ({sid})")
            if not dry_run:
                removed = cmd_delete(sid)
                if not removed and source_present(sid):
                    raise SyncVerificationError(f"Could not retire {rel}; its receipt was retained")
                if not removed:
                    counts["stale_dropped"] += 1
                new_state.pop(rel, None)
                save_state(state_path, new_state)
            if dry_run or removed:
                counts["deleted"] += 1
    if not dry_run:
        save_state(state_path, new_state)
    print(f"[{display}] DONE  " + "  ".join(f"{k}: {v}" for k,v in counts.items()) + f"  dry_run: {dry_run}")
    if not dry_run and any(counts[k] for k in ("added", "refreshed", "deleted")):
        try:
            report = TOOLS / "report-activity.sh"
            if report.exists():
                payload = dict(counts, route=display, notebook_id=notebook_id, force=force)
                subprocess.run([str(report), "--source", "agent", "--event-type", "notebooklm_refresh", "--actor", "notebooklm-refresh", "--repo", "openscaffold-wiki", "--title", f"notebooklm {display} — {counts['added']} added · {counts['refreshed']} refreshed · {counts['deleted']} deleted", "--payload", json.dumps(payload)], check=False, timeout=10)
        except Exception:
            pass


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
    _sync_files(notebook_id, display, state_file_for(label), files, dry_run, force, prune=True)


# ── Reminder notebook helpers ────────────────────────────────────────────
def iter_reminder_files():
    for rel in REMINDER_FILES:
        p = VAULT / rel
        if p.exists():
            yield p


def load_reminder_state() -> dict:
    return load_state(REMINDER_STATE_FILE)


def save_reminder_state(state: dict) -> None:
    save_state(REMINDER_STATE_FILE, state)


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
    _sync_files(REMINDER_NOTEBOOK_ID, "reminder", REMINDER_STATE_FILE, list(iter_reminder_files()), dry_run, force, prune=False)
    for rel in REMINDER_FILES:
        if not (VAULT / rel).exists():
            print(f"  ! {rel} listed in REMINDER_FILES but not on disk; notebook source retained")


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
        # A teammate's account also lists notebooks other people shared WITH them;
        # those are not theirs to route. The owner's check is unchanged.
        if MEMBER["role"] == "member" and nb.get("is_owner") is False:
            continue
        nid = nb.get("id")
        title = (nb.get("title") or "(untitled)").strip()
        if nid and not _is_known(nid):
            orphans.append((nid, title))

    for nid, title in orphans:
        # Tab-separated so the bash preflight can parse with IFS=$'\t'
        print(f"{nid}\t{title}")
    return len(orphans)


def check_caps(threshold: int = 47, cap: int = 50) -> int:
    """Warn when any routed notebook is near the per-notebook source cap.

    Prints one 'nbid<TAB>label<TAB>count<TAB>cap' line per notebook whose
    source count is >= `threshold`. Returns N warnings, or -1 on tool failure.
    Added 2026-07-06 after the-match's default bucket silently reached 50/50
    and every subsequent `source add` failed with the opaque "Failed to get
    SOURCE_ID from registration response" error. The cap is invisible until
    it bites; this makes it a preflight yellow at >= 47."""
    targets = [(nbid, label) for _prefix, nbid, label, _display in NOTEBOOK_ROUTES]
    targets.append((DEFAULT_ROUTE[0], DEFAULT_ROUTE[1]))
    if REMINDER_NOTEBOOK_ID:
        targets.append((REMINDER_NOTEBOOK_ID, "reminder"))
    seen: set[str] = set()
    warnings = 0
    for nbid, label in targets:
        if nbid in seen:
            continue
        seen.add(nbid)
        r = run_nb(["source", "list", "--notebook", nbid, "--json"])
        if r.returncode != 0:
            print(f"source list failed for {label} ({nbid}): {r.stderr}", file=sys.stderr)
            return -1
        try:
            # The CLI prints a "Matched: <full-id> (<title>)" preamble to stdout
            # when given a short-prefix notebook id (e.g. the reminder's
            # "ab4b7ccb") before emitting the JSON. Skip to the first JSON
            # character so short ids parse the same as full UUIDs.
            out = r.stdout
            starts = [i for i in (out.find("{"), out.find("[")) if i != -1]
            if not starts:
                raise ValueError("no JSON object/array found in CLI output")
            data = json.loads(out[min(starts):])
        except Exception as e:
            print(f"source list JSON parse failed for {label}: {e}", file=sys.stderr)
            return -1
        sources = data if isinstance(data, list) else data.get("sources", [])
        if len(sources) >= threshold:
            print(f"{nbid}\t{label}\t{len(sources)}\t{cap}")
            warnings += 1
    return warnings


def check_tracked(repair: bool = False) -> int:
    """Assert every state entry names a source that actually exists.

    THE INVARIANT THIS ENFORCES: for each bucket, every state entry's source_id
    is present in that bucket's notebook. A tracked-but-absent entry is the worst
    state the system can be in, because it is silent and self-perpetuating — the
    mtime shortcut in sync_route reports the file "unchanged" on every run, so the
    source is never re-uploaded and nothing ever notices it is gone.

    That is not hypothetical. Seventeen entries were in this state on 2026-08-01:
    three from a prune whose exclusions never reached the manifest (2026-07-14),
    six replaced by a run whose state write was lost (2026-07-27), one eaten by
    the basename ghost-dupe sweep (2026-07-31), and seven destroyed outright by
    cmd_replace deleting before an add that then failed at the source cap
    (2026-07-14 onwards). Every one of them was invisible for weeks. State said
    the notebook had them; the notebook did not.

    Prints one 'label<TAB>rel_path<TAB>source_id' line per absent entry and
    returns the count, so the preflight can treat non-zero as RED.

    With repair=True, drops each absent entry so the next refresh re-adds the
    file. Repair is safe because the local file is the source of truth — worst
    case the next run re-uploads content that was already correct.
    """
    buckets = plan_routing()
    absent_total = 0
    for label, paths in buckets.items():
        if not paths:
            continue
        nbid, _, display = route_for_label(label)
        state_path = state_file_for(label)
        state = load_state(state_path)
        if not state:
            continue
        r = run_nb(["source", "list", "--notebook", nbid, "--json"])
        if r.returncode != 0:
            print(f"source list failed for {display} ({nbid}): {r.stderr}", file=sys.stderr)
            return -1
        try:
            out = r.stdout
            starts = [i for i in (out.find("{"), out.find("[")) if i != -1]
            data = json.loads(out[min(starts):])
        except Exception as e:
            print(f"source list JSON parse failed for {display}: {e}", file=sys.stderr)
            return -1
        sources = data if isinstance(data, list) else data.get("sources", [])
        live_ids = {(s.get("id") or s.get("source_id")) for s in sources}
        absent = [rel for rel, e in state.items()
                  if e.get("source_id") not in live_ids]
        for rel in absent:
            print(f"{display}\t{rel}\t{state[rel].get('source_id')}")
        absent_total += len(absent)
        if repair and absent:
            for rel in absent:
                del state[rel]
            save_state(state_path, state)
            print(f"  → {display}: dropped {len(absent)} absent entr"
                  f"{'y' if len(absent) == 1 else 'ies'}; next refresh re-adds "
                  f"{'it' if len(absent) == 1 else 'them'}", file=sys.stderr)
    return absent_total


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
    parser.add_argument("--check-caps", action="store_true",
                        help="warn when a routed notebook is within 3 sources of the "
                             "50-source cap. Print one 'ID<TAB>label<TAB>count<TAB>cap' "
                             "line per near-full notebook. Exit 0 clean, 1 if warnings, "
                             "2 on tool failure. Used by tools/limitless-preflight.sh.")
    parser.add_argument("--count-routed", metavar="LABEL",
                        help="print how many wiki pages ROUTE to LABEL's bucket and exit. "
                             "Pairs with --check-caps so the preflight can report COVERAGE "
                             "(how many routed pages are actually in the notebook) rather "
                             "than only the cap. Added 2026-08-24, when 'wiki 48/50' turned "
                             "out to mean 47 of 95 routed pages had never made it in and "
                             "every query against that bucket was silently seeing half the "
                             "wiki. Offline: reads the filesystem, never the API.")
    parser.add_argument("--newest-routed", metavar="LABEL",
                        help="print the newest mtime (epoch seconds, 0 if none) of the wiki pages "
                             "routed to LABEL and exit. Offline. Used by the preflight for a "
                             "teammate's default bucket, whose routing differs from the owner's.")
    parser.add_argument("--check-coverage", action="store_true",
                        help="compare NotebookLM's notebooks against routing + IGNORED_NOTEBOOKS. "
                             "Print orphans (one per line, ID<TAB>title) and exit. "
                             "Exit 0 if all known, 1 if N orphans, 2 on tool failure. "
                             "Used by tools/limitless-preflight.sh.")
    parser.add_argument("--check-tracked", action="store_true",
                        help="assert every state entry names a source that actually "
                             "exists in its notebook. Print one "
                             "'label<TAB>path<TAB>source_id' line per tracked-but-absent "
                             "entry. Exit 0 clean, 1 if any absent, 2 on tool failure. "
                             "This is the invariant whose absence let 17 sources go "
                             "missing unnoticed for weeks — treat non-zero as RED.")
    parser.add_argument("--repair-tracked", action="store_true",
                        help="with --check-tracked, drop each absent entry so the next "
                             "refresh re-adds the file (the local file is the source of "
                             "truth, so the worst case is re-uploading correct content).")
    only_choices = ["wiki", "reminder", "all-projects"] + PROJECT_LABELS
    parser.add_argument("--only", choices=only_choices,
                        help="run only one route. 'wiki' = default bucket (cdaa7a43) only; "
                             "'all-projects' = every per-project route, skip wiki default and reminder; "
                             "<project> = just that notebook; 'reminder' = ab4b7ccb only. Default: all.")
    args = parser.parse_args()

    if MEMBER["role"] == "unset":
        # A teammate with no notebooks of their own. Never fall back to the owner's.
        print(f"ERROR: {MEMBER['login']} has no NotebookLM notebooks of their own for this vault yet. "
              "Make them: python3.11 tools/notebooklm-member-setup.py --shared <projects you share>",
              file=sys.stderr)
        sys.exit(2)

    if args.newest_routed:
        newest = 0
        for p in plan_routing().get(args.newest_routed, []):
            newest = max(newest, int(p.stat().st_mtime)) if p.exists() else newest
        got = log_export_plan()
        if got and any(got[1] / n in plan_routing().get(args.newest_routed, []) for n in got[3].files):
            newest = max(newest, int(got[0].stat().st_mtime))
        print(newest)
        sys.exit(0)

    # --count-routed is filesystem-only and must run BEFORE the auth check:
    # it never touches the API, and gating it on auth made the preflight's
    # coverage line hang on `notebooklm auth check` (observed 2026-08-24).
    if args.count_routed:
        print(len(plan_routing().get(args.count_routed, [])))
        sys.exit(0)

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

    # --check-caps: same exit semantics as --check-coverage.
    if args.check_caps:
        n = check_caps()
        if n < 0:
            sys.exit(2)
        sys.exit(0 if n == 0 else 1)

    # --check-tracked: same exit semantics again. With --repair-tracked it also
    # drops the absent entries, so a follow-up refresh re-adds the files.
    if args.check_tracked:
        n = check_tracked(repair=args.repair_tracked)
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

    if any((VAULT / _NB_MANIFEST.get("log_exports", {}).get("path", "")).is_file() and p.parent == STATE_DIR / "notebooklm-exports" for label in labels_to_run for p in plan_routing().get(label, [])):
        prepare_log_exports(args.dry_run, verify_only=args.verify_existing)

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
                # Files outside the vault that this notebook should carry (the repo's rules
                # file, its changelog …) — see tools/notebooklm_external.py. Added 2026-09-25
                # so no session uploads them by hand again.
                if _EXTERNAL is not None:
                    result = _EXTERNAL.sync_externals(sys.modules[__name__], label, args.dry_run, force=args.force)
                    if result.get("failed"):
                        raise SyncVerificationError(f"External route {label} failed: {result['failed']}")

    if do_reminder:
        if args.seed:
            seed_reminder(args.dry_run)
        else:
            sync_reminder(args.dry_run, force=args.force)
            # The reminder notebook's files from outside the vault — the Hub repo's rules
            # file, as hub-CLAUDE.md (2026-10-03; it had been kept by hand and fell 11 days
            # behind). Same mechanism as the routes above.
            if _EXTERNAL is not None:
                result = _EXTERNAL.sync_externals(sys.modules[__name__], _EXTERNAL.REMINDER_LABEL,
                                                 args.dry_run, force=args.force)
                if result.get("failed"):
                    raise SyncVerificationError(f"External reminder route failed: {result['failed']}")


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
        if stale:
            raise SyncVerificationError(f"{display}: {stale} existing sources failed content verification")

    for label in labels_to_run:
        nbid, _, display = route_for_label(label)
        _verify_batch(state_file_for(label), nbid, display)

    if do_reminder:
        _verify_batch(REMINDER_STATE_FILE, REMINDER_NOTEBOOK_ID, "reminder")


if __name__ == "__main__":
    try:
        inspection = any(flag in sys.argv for flag in (
            "--help", "--dry-run", "--count-routed", "--newest-routed", "--check-coverage",
            "--check-caps", "--check-tracked")) and "--repair-tracked" not in sys.argv
        if inspection:
            # Read-only preflight/planning must coexist with a refresh writer
            # and must never collect its recovery journals.
            main()
        else:
            with _SAFETY.sync_lock(STATE_DIR):
                main()
                _SAFETY.finish_receipts(STATE_DIR)
    except (SyncVerificationError, RuntimeError, _LOG_EXPORTS.LogExportError) as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
