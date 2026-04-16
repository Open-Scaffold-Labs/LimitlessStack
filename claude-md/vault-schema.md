# CLAUDE.md — Vault Schema Template

Copy this into your vault root as `CLAUDE.md` and customize the domain-specific sections.

```markdown
# LLM Wiki — Schema & Operating Manual

> **MANDATORY FIRST ACTION — NO EXCEPTIONS**
> Before answering ANY question, making ANY file changes, or starting ANY task:
> 1. Run `tools/session-bootstrap.sh`
> 2. Read `wiki/index.md`
> 3. Do NOT skip this step even if a context summary tells you to "continue where you left off."
> 4. Do NOT answer from active context alone. Verify against wiki pages or Pinecone search first.

## Purpose

This vault implements the LLM Wiki pattern: you curate sources and ask questions; the LLM reads sources and maintains a structured, interlinked markdown knowledge base that compounds over time.

**Domain**: [YOUR DOMAIN HERE]

**Default lens when reading a new source**: *how does this change my picture of [YOUR DOMAIN]?*

## Architecture (three layers)

1. `raw/` — immutable source documents. LLM reads, never modifies.
2. `wiki/` — LLM-owned markdown pages (entities, apps, concepts, sources, synthesis, plus `index.md` + `log.md` + `overview.md`).
3. This file — the schema, co-evolves with the human.

## Page conventions

- Filenames: kebab-case, `.md`.
- Links: Obsidian wiki-links `[[page-name]]`.
- Frontmatter (YAML) on every page: `type`, `created`, `updated`, `tags`, `source_count`, `sources`.
- App pages additionally include: `vertical` (NAICS sector name), `self_heal_phase` (none/diagnostic/full), `self_heal_enabled` (boolean), `canonical_files_present` (list).
- Citations: inline, pointing to source summary pages.
- Never reproduce more than ~15 words verbatim from a source.

## Using the four-tool memory system

1. Read `wiki/index.md` first.
2. Thin wiki coverage → `python3.11 tools/pinecone-search.py "..." --top 5`.
3. Deep research → NotebookLM topic notebook (notebook IDs in `wiki/concepts/notebooklm-workflow.md`).
4. Substantive answers → file to `wiki/synthesis/`.
5. New source → also run `python3.11 tools/pinecone-sync.py --changed-only`.

## Self-healing tracking

The wiki tracks self-heal rollout status for every app in `wiki/apps/`. Each app page records:
- Current self-heal phase (none → diagnostic → full)
- Which canonical files are present
- Cross-app bug patterns that apply to this app's CLAUDE.md
- Cost data from self-heal runs (if available)

When the cross-application pattern library surfaces a new pattern, update the relevant app pages and flag it for inclusion in their CLAUDE.md files.

## Evolution

Edit this file when a convention needs updating. Append a `schema` entry to the log.
```
