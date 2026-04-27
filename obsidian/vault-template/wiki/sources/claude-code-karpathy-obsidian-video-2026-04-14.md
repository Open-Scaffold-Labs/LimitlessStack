---
type: source
created: 2026-04-14
raw_path: https://www.youtube.com/watch?v=eglVxLaWRUU
source_type: youtube
author: Jack Roberts
title: "Claude Code + Karpathy's Obsidian = New Meta"
duration: "19:43"
date: 2026-04
tags: [methodology, llm-wiki, obsidian, notebooklm, pinecone]
notebooklm_source_id: 5e06a5c3-d1d6-45cc-8226-64f44aaa7aac
---

# Source: "Claude Code + Karpathy's Obsidian = New Meta" (video)

Jack Roberts' walkthrough of a four-tool LLM memory system built around Karpathy's [[concepts/llm-wiki-pattern|LLM Wiki pattern]]. The framing Matt wants us to apply to [[entities/openscaffold|OpenScaffold]].

## Key framing — "four tools, four jobs"

| Tool | Role | Analogy |
|---|---|---|
| `CLAUDE.md` | Rules / voice / conventions | Identity |
| Obsidian + LLM wiki | Active reasoning, structured relationships | Workshop |
| NotebookLM | Topic-specific deep research across many sources | Research desk |
| Pinecone (vector DB) | Perfect recall over massive static archives | Warehouse |

The Obsidian-only system breaks past ~10,000 files: token costs balloon, sessions slow down, the graph becomes unusable. Pinecone fills that gap for high-volume, low-structure material you rarely need to reason *over* but occasionally need to recall.

## Chapter breakdown

1. **The AI amnesia problem** — models hallucinate or forget across long sessions. Goal: self-updating memory that gets smarter per interaction.
2. **The "personal Wikipedia" concept** — Karpathy's LLM Wiki: `raw/` (immutable sources) + `wiki/` (LLM-owned pages). Compiled once, kept current — not re-derived per query.
3. **Setting up the visual layer** — install Obsidian, use Graph View as the visualisation layer.
4. **System initialisation** — paste Karpathy's LLM Wiki premise into Claude Code (or Antigravity) at the start, so Claude acts as a wiki maintainer not a chatbot.
5. **Compounding effect vs RAG** — classic RAG: chunks → answer → forget. LLM Wiki: one source → 15 pages updated → compounds.
6. **Three-layer architecture** — `raw/`, `wiki/`, `CLAUDE.md`. Source of truth, LLM layer, rulebook.
7. **Core operations** — ingest, query, lint. `index.md` as catalog, `log.md` as append-only history. Lint every few weeks.
8. **Practical run — a "LifeOS" wiki** — co-author rules with Claude on the first session; establish voice and domain.
9. **Web clipper hack** — Obsidian Web Clipper browser extension writes directly into `raw/` with custom templates.
10. **Limitations** — system scales linearly; ~10k files is the wall.
11. **"New Meta" — Obsidian + Pinecone** — hybrid. Obsidian for thinking, Pinecone for recall over massive static archives (e.g. transcripts).
12. **Unified four-tool system** — `CLAUDE.md` + Obsidian + Pinecone + NotebookLM = identity + workshop + warehouse + research.

## Extracted claims / rules

- Give Claude the "rules of the game" at the start of every session (read `CLAUDE.md` first).
- `raw/` is immutable. `wiki/` is LLM-owned. Never blur the line.
- `index.md` + `log.md` are navigation/audit infrastructure — not optional.
- Lint runs: every few weeks. Contradictions, orphans, stale claims, coverage gaps.
- Web Clipper → `raw/` lets you ingest web content without manual plumbing.
- Obsidian-only breaks at ~10k files; Pinecone is the escape hatch for volume.
- **Obsidian for thinking, Pinecone for recall** is the key mental split.

## Pages touched / created

- [[concepts/llm-wiki-pattern]] *(new concept page)*
- [[synthesis/memory-architecture]] *(new — OpenScaffold-specific application of the four-tool model)*
- Informs future updates to [[CLAUDE.md|the schema]] in this vault.
