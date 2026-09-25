"""
Limitless Stack project manifest.

Lives at the root of any vault using the Limitless Stack tools.
The preflight script (tools/limitless-preflight.sh) and the refresh script
(tools/notebooklm-wiki-refresh.py) read configuration from here.

To re-create this manifest from scratch:
    ~/LimitlessStack/bin/limitless-stack-init <project_id> <target>

Schema:
  PROJECT_ID    — kebab-case unique identifier (REQUIRED)
  DESCRIPTION   — one-line human description
  CHECKS        — list of optional preflight checks. The mandatory checks
                  (claude_md, obsidian, notebooklm, sync_check, anti_patterns)
                  always run regardless of this list.
                  Optional checks: pinecone
  OBSIDIAN      — config dict
  PINECONE      — config dict (only if 'pinecone' in CHECKS)
  NOTEBOOKLM    — config dict (REQUIRED — every project must have a notebook)
  SYNC_CHECK    — config dict
"""

PROJECT_ID = "__PROJECT_ID__"
DESCRIPTION = "__DESCRIPTION__"

# Optional checks. Mandatory checks (claude_md, obsidian, notebooklm,
# sync_check, anti_patterns) always run regardless.
# Add "pinecone" once YOUR Pinecone index exists and YOUR key is in the Keychain.
CHECKS = []

# Only for a vault you SHARE with teammates (.authors.json): your GitHub login. The vault's
# upkeep checks then run on your Roll Call only, and each teammate's Roll Call shows just
# their own machine, sign-ins and task file. Leave it out for a vault only you use.
# VAULT_OWNER = "your-github-login"

# YOUR Pinecone index (create it in your own Pinecone account — see the onboarding guide).
# tools/pinecone-sync.py and tools/pinecone-search.py read the index name from here.
PINECONE = {
    "index": "__PROJECT_ID__",
    "repos_dir": "raw/repos",
    "state_file": "tools/.pinecone-sync-state.json",
}

OBSIDIAN = {
    "wiki_dir": "wiki",
    "expected_min_pages": 5,
}

NOTEBOOKLM = {
    # Per-project routes: each tuple is (path_prefix, notebook_id, state_label, display_label).
    # Add an entry per wiki/apps/<name>.md that should mirror to a dedicated notebook.
    # Leave empty if all wiki content goes to the default bucket.
    "routes": [],

    # Default bucket — every wiki/*.md not matched by 'routes' lands here.
    # REQUIRED: replace REPLACE_WITH_NEW_NOTEBOOK_ID with the actual notebook
    # ID after creating the project's main NotebookLM notebook.
    "default": ("REPLACE_WITH_NEW_NOTEBOOK_ID", "wiki", "wiki"),

    # Curated reminder bucket — read at session start. Files listed here are
    # mirrored into a small reminder notebook so the next session's first
    # NotebookLM query picks up project rules + recent mistakes.
    "reminder": {
        "notebook_id": "REPLACE_WITH_REMINDER_NOTEBOOK_ID",
        "files": [
            "CLAUDE.md",
            "wiki/synthesis/claude-anti-patterns.md",
        ],
        "title_aliases": {
            # If a reminder file is uploaded with a renamed title (to disambiguate
            # from another project's CLAUDE.md, etc.), map it here.
        },
    },

    # Notebooks that exist in NotebookLM but are intentionally NOT routed.
    # Add notebooks here if they're curated reference buckets you don't want
    # the wiki refresh to manage. Format: {notebook_id: "human description"}.
    "ignored": {},

    # Path prefixes that should NOT be mirrored to ANY notebook (e.g., raw
    # source summary pages that have a per-project notebook upstream).
    "exclude_paths": [],
}

SYNC_CHECK = {
    # Informational only: the tools locate the canonical via $LIMITLESS_STACK_HOME
    # (default ~/LimitlessStack). Set that variable if you cloned it elsewhere.
    "limitless_stack_home": "~/LimitlessStack",
}

# ── Optional: NotebookLM sources that live OUTSIDE the vault (added 2026-09-25) ──────────
# Files a notebook should carry that are not wiki pages (a repo's rules file, its changelog).
# tools/notebooklm_external.py keeps them current through the refresh tool: each gets a
# DISTINCT title, is re-uploaded only when its content changes, and any copy titled with one
# of hand_titles (a hand upload) is removed once the managed copy is verified — its text is
# saved to NOTEBOOKLM_REMOVED_BACKUP first. Owner only. Leave these out if you have none.
# NOTEBOOKLM_EXTERNAL = [
#     {"path": "~/my-repo/CLAUDE.md", "label": "<route label>",
#      "title": "my-repo-rules-CLAUDE.md", "hand_titles": ["CLAUDE.md"]},
# ]
# NOTEBOOKLM_FROZEN = {"<notebook id prefix>": ["<title of a dated source kept on purpose>"]}
# NOTEBOOKLM_ACCOUNTED = ["<notebook id prefix>"]   # every source there must be managed or frozen
# NOTEBOOKLM_REMOVED_BACKUP = "~/somewhere-private/notebooklm-removed"
