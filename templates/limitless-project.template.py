"""
Limitless Stack project manifest.

Lives at the root of any vault using the Limitless Stack tools.
The preflight script (tools/limitless-preflight.sh) and the refresh script
(tools/notebooklm-wiki-refresh.py) read configuration from here.

To re-create this manifest from scratch:
    /Users/matthewlavin/LimitlessStack/bin/limitless-stack-init <project_id> <target>

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
CHECKS = []

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
    "limitless_stack_home": "/Users/matthewlavin/LimitlessStack",
}
