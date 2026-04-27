# Obsidian — Structured Knowledge Base

Obsidian is the wiki layer of the Limitless Stack. It implements the LLM Wiki pattern: humans curate sources, the LLM maintains a structured, interlinked markdown knowledge base that compounds over time.

## Role in the Stack

Obsidian owns the structured knowledge. Every entity, app, concept, decision, and source summary lives here as interlinked markdown pages with YAML frontmatter. As Open Scaffold scales to 100 vertical apps, the wiki is what keeps institutional knowledge organized — architecture decisions, rollout status, cross-app patterns, and the relationships between all of it.

## Role in Self-Healing

Obsidian tracks the self-healing rollout across the entire app fleet:

- **App pages** (`wiki/apps/`) record each app's self-heal phase (none → diagnostic → full), which canonical files are present, and the vertical it serves
- **Synthesis pages** (`wiki/synthesis/`) capture cross-app bug patterns — when the same type of bug surfaces across multiple apps, that pattern gets filed here
- **The pattern feedback loop**: patterns discovered in synthesis pages get folded back into each app's CLAUDE.md as "known patterns and common pitfalls," improving future diagnostic accuracy

This is the compounding knowledge loop at the center of the whole system.

## What's in this folder

`vault-template/` contains the directory skeleton for a new vault:

```
vault-template/
├── wiki/
│   ├── index.md       # catalog of every page
│   ├── log.md         # chronological append-only log
│   └── overview.md    # top-level synthesis
└── raw/               # empty — user clones repos here
```

When setting up a new Limitless Stack instance, copy this template and add the CLAUDE.md schema from `claude-md/vault-schema.md`.

## Page taxonomy

| Type | Location | Purpose |
|---|---|---|
| Entity | `wiki/entities/` | People, orgs |
| App | `wiki/apps/` | One page per app — architecture, vertical, self-heal status, rollout phase |
| Concept | `wiki/concepts/` | Patterns, protocols, terms |
| Source | `wiki/sources/` | One summary per raw source ingested |
| Synthesis | `wiki/synthesis/` | Filed query answers, lint reports, cross-app bug patterns |

## Core operations

- **Ingest** — New source lands in `raw/`, LLM creates summary page, updates entity/concept/app pages, flags contradictions, updates index and log.
- **Query** — Follow the four-tool lookup order (wiki first, then Pinecone, then NotebookLM, then file the answer back).
- **Lint** — Periodic health check for contradictions, stale claims, orphans, missing pages, broken links, coverage gaps.

## Integration points

- **CLAUDE.md** — The vault schema defines how the LLM interacts with the wiki. Each app's CLAUDE.md references wiki patterns.
- **Pinecone** — `raw/` content is indexed in Pinecone for semantic search when the wiki is thin. Cross-app bug patterns from synthesis pages also feed Pinecone.
- **NotebookLM** — Wiki content can be uploaded as sources to topic notebooks for deep research.
- **Hub Workspace** — The vault lives in Hub Workspace's workspace, accessible to all dispatched agents.
- **Paperclip** — Paperclip reads the wiki for context when coordinating rollout and budgets.
- **Self-healing** — Wiki tracks rollout status per app and feeds the cross-application pattern library back into CLAUDE.md files.
