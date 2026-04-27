---
type: concept
created: 2026-04-14
updated: 2026-04-21
tags: [tooling, operations, notebooklm]
source_count: 2
sources: [openfirehouse-claude-md, firehazmat-claude-md]
---

# NotebookLM workflow

Google NotebookLM is an active **operational tool** in [[openscaffold|Open Scaffold Labs]] — not just a research aid. Coding sessions on OpenFirehouse and FireHazmat begin with a mandatory NotebookLM query and end with refreshing sources.

## Two access paths

Matt has both available. Use the right tool for the job.

### 1. Claude in Chrome extension (preferred for interactive work)

- The extension drives **Matt's live, logged-in Chrome session** directly — no auth plumbing.
- Confirmed working as of 2026-04-14. Matt is logged in to NotebookLM as `mlav19911114@gmail.com`.
- Tools: `mcp__Claude_in_Chrome__navigate`, `find`, `left_click`, `type`, `get_page_text`, etc.
- Use for: asking a notebook a question, adding a single source, checking a response, eyeballing results.
- No cookie refresh ever needed — sidesteps the hardware-security-key problem entirely.

### 2. `notebooklm-py` CLI (preferred for batch / headless work)

- Uses Playwright browser automation with a stored session at `~/.notebooklm/storage_state.json` — **on Matt's Mac**, not in any sandbox.
- **Install** (one-time, already done on Matt's Mac): `pip install "notebooklm-py[browser]" && playwright install chromium`
- **Login** (one-time, already done; re-run only when session expires): `notebooklm login` — opens a Playwright browser on the Mac, Matt completes Google sign-in, presses Enter in the terminal. Auth saved automatically to `~/.notebooklm/storage_state.json`.
- **Verify**: `notebooklm auth check --test` — confirms token fetch works.
- **Skill install** (already done): `notebooklm skill install` — installs the v0.3.4 skill to `~/.claude/skills/notebooklm/SKILL.md`.
- The old `browser-cookie3` cookie-extraction workaround is **no longer needed** — `notebooklm login` handles auth cleanly via Playwright.
- Use for: bulk uploads (e.g. mirroring 20+ wiki pages), one-off scripted refreshes, anything headless that genuinely needs the API, or agent-driven research.

### 3. Running `notebooklm` from Claude's sandbox — route via desktop-commander

Claude's sandbox is a **separate, ephemeral Linux environment**, not Matt's Mac. The setup above (CLI, `storage_state.json`, Playwright chromium, skill install) does **not** exist in the sandbox and **cannot be meaningfully recreated there**:

- The sandbox has no display Matt can interact with → `notebooklm login`'s Playwright browser has nowhere to show the Google OAuth flow → login can't complete.
- Everything in the sandbox is wiped between sessions → even if a session managed to install + authenticate, the next session would start empty.
- Attempting `pip install notebooklm-py[browser] && playwright install chromium` downloads ~106 MB of chromium, then hits the OAuth dead end.

**Correct pattern — execute every `notebooklm` call on Matt's Mac via desktop-commander:**

```
mcp__desktop-commander__start_process(
  command="notebooklm use ab4b7ccb && notebooklm ask 'question…'",
  shell="zsh",
  timeout_ms=90000
)
```

This runs the real CLI on the Mac, with the live auth, against the real notebooks. Every subcommand works this way — `ask`, `source list`, `source add`, `source refresh`, `generate audio`, `download`, `artifact list`, `artifact wait`, `metadata`, `skill status`. No sandbox plumbing required.

> [!warning] Anti-pattern this replaces
> If a session starts trying to `pip install notebooklm-py`, `playwright install chromium`, or run `notebooklm login` in the sandbox: stop. That's [[synthesis/claude-anti-patterns|anti-pattern #10]]. The setup is already done on the Mac; use desktop-commander.

## Notebooks in use

| Notebook ID | Title | Purpose |
|---|---|---|
| `cdaa7a43` | OpenScaffold Wiki | Default bucket — wiki pages **not** routed elsewhere and **not** in `EXCLUDE_FROM_NOTEBOOKS`. Cross-cutting concepts, entities, most synthesis pages. Kept in sync by `tools/notebooklm-wiki-refresh.py`. |
| `f376f6e8` | FireHazmat | Per-project notebook — owns `wiki/apps/firehazmat.md` + seeded FireHazmat repo files. |
| `26a8db12` | OpenChiropractor | Per-project notebook — owns `wiki/apps/openchiropractor.md` + seeded OpenChiropractor repo files. |
| `9c8f3df0` | OpenFirehouse | Per-project notebook — owns `wiki/apps/openfirehouse.md` + active OpenFirehouse project docs (rules, recent changes, mistakes to avoid). |
| `0a072ead` | OpenSalon | Per-project notebook — owns `wiki/apps/opensalon.md` + seeded OpenSalon repo files. |
| `ca083f4f` | Limitless Stack Hub — Repo | Per-project notebook for the Hub — owns `wiki/synthesis/hub-*.md` (7 pages) + seeded Hub repo files (CLAUDE.md, README, package.json, vercel.json). |
| `733f98ef` | OpenScaffold Architecture | Canonical technical docs — 27 architecture `.docx` + 1 `.md` + openscaffold-core `CLAUDE.md`. Curated manually; not auto-refreshed. |
| `1a0a0c47` | OpenScaffold Business | 29 business docs + 72 white-papers — positioning, pricing, market thinking. |
| `9830f04f` | ERG Research | ERG 2024 — orange-page guide text extraction. |
| `ab4b7ccb` | **Limitless Stack Hub — Reminder** | **Claude's reminder layer (untouched by the routing refactor)** — curated 5-file allowlist: vault `CLAUDE.md`, [[synthesis/claude-anti-patterns]], [[concepts/limitless-stack]], [[concepts/paperclip]], [[apps/limitless-stack-hub]]. Queried at start of every session per the CLAUDE.md protocol. |

## Automated wiki mirroring — path-prefix routing

`tools/notebooklm-wiki-refresh.py` routes each `wiki/*.md` file to the correct notebook and keeps every notebook in sync. Introduced 2026-04-21 as part of the notebook-architecture rebuild (see [[synthesis/notebook-architecture-rebuild]]).

### Routing table

Routing is defined in the `NOTEBOOK_ROUTES` constant at the top of the script. The table is an ordered list of `(path_prefix, notebook_id, state_label, display_label)` entries. For each file, the **first matching prefix wins**; files matching no prefix fall through to `DEFAULT_ROUTE` (`cdaa7a43`).

| Route | Path prefix | Notebook | State file |
|---|---|---|---|
| firehazmat | `wiki/apps/firehazmat.md` | `f376f6e8` | `.notebooklm-firehazmat-state.json` |
| openchiropractor | `wiki/apps/openchiropractor.md` | `26a8db12` | `.notebooklm-openchiropractor-state.json` |
| openfirehouse | `wiki/apps/openfirehouse.md` | `9c8f3df0` | `.notebooklm-openfirehouse-state.json` |
| opensalon | `wiki/apps/opensalon.md` | `0a072ead` | `.notebooklm-opensalon-state.json` |
| hub | `wiki/synthesis/hub-` *(filename prefix — matches all 7 `hub-*.md`)* | `ca083f4f` | `.notebooklm-hub-state.json` |
| wiki *(default)* | *(anything not routed above and not excluded)* | `cdaa7a43` | `.notebooklm-wiki-state.json` |
| reminder | curated allowlist (5 files) | `ab4b7ccb` | `.notebooklm-reminder-state.json` |

Each state file maps wiki-relative path → `{mtime, source_id}`. The reminder notebook uses a hardcoded `REMINDER_FILES` allowlist rather than routing — its scope is deliberately curated, not mechanical.

### Exclusion list — files that go to no notebook

Some wiki files are deliberately **not** mirrored to any notebook. The `EXCLUDE_FROM_NOTEBOOKS` list in `tools/notebooklm-wiki-refresh.py` filters these out before routing:

| Excluded prefix | Why |
|---|---|
| `wiki/sources/firehazmat-` | Source summaries are redundant — the underlying repo files (e.g., FireHazmat's `CLAUDE.md`) are already in `f376f6e8` directly. |
| `wiki/sources/openchiropractor-` | Same reason — covered by `26a8db12`'s seeded repo files. |
| `wiki/sources/openfirehouse-` | Same reason — covered by `9c8f3df0`'s seeded repo files. |
| `wiki/sources/opensalon-` | Same reason — covered by `0a072ead`'s seeded repo files. |

Decision recorded 2026-04-21 (group (a) of the post-rebuild follow-up): listing the wiki summary alongside the raw repo file would be duplicative retrieval surface area for the same underlying content.

### CLI modes

- `python3.11 tools/notebooklm-wiki-refresh.py` — sync every route + reminder (default).
- `--seed` — first-time / post-migration: match existing notebook sources to files by filename, write all state files.
- `--dry-run` — show what would happen; no writes.
- `--only <route>` — run only one route. Accepts `firehazmat`, `openchiropractor`, `openfirehouse`, `opensalon`, `hub`, `wiki` (default bucket only), `reminder`, or `all-projects` (all 5 per-project routes, skip wiki default + reminder).
- `--skip-auth-check` — skip the `notebooklm auth check --test` gate.

Sync behavior per route: new file → add; mtime-changed file → refresh (falls back to delete+add on failure); file no longer on disk or no longer routed here → delete. The reminder notebook never deletes — its scope is curated, so deletes are a manual decision.

Runs as part of the nightly scheduled task alongside the Pinecone sync. Tolerates NotebookLM's transient "Failed to get SOURCE_ID from registration response" error — unsynced files are left in state for retry on the next nightly run.

### Adding a new per-project notebook

1. Create the notebook in NotebookLM (via Skill or CLI).
2. Seed the notebook manually with the initial repo files / key docs.
3. Append a new entry to `NOTEBOOK_ROUTES` in `tools/notebooklm-wiki-refresh.py` (most specific prefixes first).
4. Append a matching entry to the preflight loop in `tools/limitless-preflight.sh` (Section `[5/7]`).
5. Update the "Routing table" above.
6. Run `python3.11 tools/notebooklm-wiki-refresh.py --seed --only <label>` to write the initial state file.

## Preflight freshness checks

`tools/limitless-preflight.sh` Section `[5/7]` (invoked by Roll Call at session start) now verifies freshness for every notebook:

- **Per-project routes (4 of them)** — compares the routed file's mtime against the route's state-file mtime. Warns if the file has been edited since the last refresh, and points the fix command at `--only <label>` so a single stale route is scoped to just that notebook.
- **Default bucket (`cdaa7a43`)** — computes `WIKI_DEFAULT_NEWEST_TS` excluding the 4 per-project paths, then compares it against `.notebooklm-wiki-state.json`'s mtime. This avoids falsely flagging cdaa7a43 as stale when the most-recent wiki edit went to a per-project notebook.
- **Reminder notebook (`ab4b7ccb`)** — iterates the curated `REMINDER_FILES` allowlist and warns if any of them has been edited since the last reminder refresh.

Each check falls back to a `--seed --only <label>` warning if the state file is missing entirely.

## Sources registered in notebook `9c8f`

- `8ba7ef` — CLAUDE.md
- `7de6d9` — OpenFirehouse `UPDATES.md`
- `903dab` — FireHazmat `UPDATES.md`

## Standard commands

```bash
notebooklm list                      # list notebooks
notebooklm use <notebook-id>         # set active
notebooklm ask "..."                 # query active notebook
notebooklm source add <url-or-file>  # add a source
notebooklm source refresh <id>       # re-ingest a source
notebooklm generate audio|quiz       # generate artefacts
notebooklm auth check --test         # diagnose auth issues
notebooklm skill status              # check skill installation
```

## Session protocol (from each project's CLAUDE.md)

- **Start of session**: `notebooklm use 9c8f && notebooklm ask "What are the key rules, recent changes, and mistakes to avoid for this project?"`
- **End of session**:
  1. Update `UPDATES.md` in both OpenFirehouse and FireHazmat.
  2. Commit and push both to Open-Scaffold-Labs.
  3. `notebooklm source refresh 8ba7ef / 7de6d9 / 903dab` so next session sees current state.

## Use for ERG research

`pdfplumber` cannot reliably extract the **ERG 2024** orange-pages (guides 111–172) because they're two-column. The project uses NotebookLM instead:

1. `notebooklm use 9830`

2. `cd ~/openfirehouse && python3.11 scripts/extract-erg-guides.py` — batch queries (4 guides at a time) produce `/tmp/erg-guides-parsed/all_guides.json`.
3. `python3.11 scripts/update-guides-from-json.py` → push into `fs_hazmat_guides`.
4. `cd ~/FireHazmat && node scripts/extract-data.js` → re-export `hazmat.json` for the iOS app (remember to bump `DATA_VERSION`).

## Relationships

- Core to the ops loop for [[apps/openfirehouse]] and [[apps/firehazmat]]
- Feeds [[concepts/erg-2024]] data into the apps
- Auth is now handled cleanly via `notebooklm login` (Playwright-based)

## Open questions

- Are other OpenScaffold apps (Salon, Chiropractor) expected to adopt the same NotebookLM protocol, or is it specific to the fire-department family?

## Sources

- [[sources/openfirehouse-claude-md-2026-04-14]]
- [[sources/firehazmat-claude-md-2026-04-14]]
