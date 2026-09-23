---
type: concept
created: 2026-09-23
updated: 2026-09-23
tags: [tooling, operations, notebooklm]
source_count: 0
sources: []
---

# NotebookLM workflow

NotebookLM is an **operational tool** in this vault, not only a research aid. Sessions begin by
asking the **reminder notebook** for the current operating rules and end by **refreshing** the
notebooks from the wiki. Every notebook here is YOURS — created in your Google account and
declared in `.limitless-project.py` at the vault root.

## How Claude reaches NotebookLM

Always through the **`notebooklm` skill**, which drives the `notebooklm` CLI (notebooklm-py).

- **Install** (done by `install.sh`): `pip install "notebooklm-py[browser]"` + `playwright install chromium`.
- **Sign in once**, on your own computer: `notebooklm login` opens a browser for your Google
  sign-in and saves the session under `~/.notebooklm/`.
- **Check**: `notebooklm auth check --test` — the `--test` flag makes a real network call; a check
  without it only proves the cookie file parses.
- **Sandboxed Claude sessions** (e.g. a cloud workspace) do not have your sign-in. Run the CLI on
  your own computer (through a desktop bridge such as Desktop Commander), never by installing and
  logging in inside the sandbox — it has no display for the sign-in and is wiped between sessions.

## Your notebooks

| Notebook | Purpose | Declared in the manifest as |
|---|---|---|
| Default wiki notebook | Mirrors the wiki pages not routed elsewhere | `NOTEBOOKLM["default"]` |
| Reminder notebook | A short, curated list of files Claude reads FIRST each session: `CLAUDE.md`, the anti-patterns page, and whatever else defines how you work | `NOTEBOOKLM["reminder"]` (`notebook_id` + `files`) |
| Per-project notebooks (optional) | One per large topic, fed by a path prefix | `NOTEBOOKLM["routes"]` |

Create them with `notebooklm create "<name>"` and copy each returned ID into the manifest.

## Mirroring the wiki

`python3.11 tools/notebooklm-wiki-refresh.py` uploads changed wiki files to the right notebook
(first matching route wins; everything else goes to the default notebook) and the reminder files to
the reminder notebook.

- `--only <label>` refreshes one notebook; `--dry-run` shows what would change.
- **Coverage rule:** every notebook in your account must appear in the manifest (a route, the
  default, the reminder, or `ignored`). Roll Call flags any that don't.
- **Source cap:** notebooks hold a limited number of sources (50 on the standard plan). Keep the
  reminder list short and route large topics to their own notebooks.

## Verifying a refresh — the part that matters

- The script prints `refreshed · verify_failed · upload_failed`. **Non-zero `verify_failed` or
  `upload_failed` is a stop**, not a warning.
- **A timed-out tool call is not a failed job.** Big files take minutes to index; check the notebook
  before re-running, or you will re-upload the same file again and again.
- **Evidence, weakest to strongest:** the state file (a receipt) → asking the notebook (a sample; it
  can be wrong both ways) → `notebooklm source fulltext <source_id>` (the indexed text itself).
  Search the fulltext with plain prose — the indexer strips markdown punctuation.
- **Duplicates:** `python3.11 tools/notebooklm-dedupe.py --notebook <id> --state <label>` (add
  `--apply` only after reading the dry run).

## Relationships

- [[concepts/llm-wiki-pattern]] — the pattern this vault implements.
- [[synthesis/claude-anti-patterns]] — lives in the reminder notebook.
