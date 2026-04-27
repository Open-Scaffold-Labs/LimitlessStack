---
type: concept
created: 2026-04-14
updated: 2026-04-14
tags: [methodology, llm-wiki, meta]
source_count: 1
sources: [claude-code-karpathy-obsidian-video-2026-04-14]
---

# LLM Wiki pattern

The methodology this whole vault is built on: an LLM incrementally builds and maintains a structured markdown knowledge base, instead of doing RAG retrieval from raw documents on every query.

## Summary

Original pattern from **Andrej Karpathy** (writer, ex-OpenAI/Tesla). The human curates sources and asks questions; the LLM reads sources and writes into a persistent, interlinked wiki. Knowledge *compounds* — each new source can touch many pages — rather than being re-derived from scratch every time.

## The three layers

1. `raw/` — immutable source documents (LLM reads, never edits).
2. `wiki/` — LLM-owned markdown pages.
3. `CLAUDE.md` — the schema / rulebook / voice for the LLM.

## Core operations

- **Ingest** — new source → summary page + entity/concept updates + log entry.
- **Query** — read `index.md` first, follow wiki-links, answer with citations, optionally file the answer as a new synthesis page.
- **Lint** — periodic health check for contradictions, orphans, stale claims, coverage gaps.

## Difference from classic RAG

| | Classic RAG | LLM Wiki |
|---|---|---|
| Processing | Per-query | Per-source (up front, once) |
| Memory | Stateless | Compounding |
| Structure | Vector chunks | Interlinked markdown pages |
| One source touches… | Itself only | 10–15 wiki pages |
| Human role | Query | Curate + question |
| LLM role | Retrieve + answer | Read + write + maintain |

## Scaling wall

Obsidian-only breaks at ~10,000 files. Token costs, session latency, and graph readability all collapse past that threshold. See [[synthesis/memory-architecture]] for the four-tool answer (Obsidian + NotebookLM + Pinecone + `CLAUDE.md`).

## Relationships

- Implemented by this vault
- Extended in [[synthesis/memory-architecture]] — applies the pattern to [[entities/openscaffold|OpenScaffold]]
- Original source: [[sources/claude-code-karpathy-obsidian-video-2026-04-14]]

## Sources

- [[sources/claude-code-karpathy-obsidian-video-2026-04-14]]
