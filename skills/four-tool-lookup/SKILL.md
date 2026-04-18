---
name: four-tool-lookup
description: Before making any substantive claim about Open Scaffold Labs — architecture, apps, tools, people, decisions, operating rules, CLAUDE.md protocol, the Limitless Stack, Paperclip, OpenFirehouse, FireHazmat, or any of the other verticals — run this skill. It enforces the canonical wiki → Pinecone → NotebookLM lookup order so answers are grounded in the vault rather than improvised from active context. Use it whenever the user asks a question that *sounds* like you should already know the answer, whenever you're about to cite internal conventions or architecture decisions, and whenever you're about to recommend a change that touches OpenScaffold infrastructure.
---

# Four-Tool Lookup

The OpenScaffold vault exists because reasoning from active context drifts. This skill is the discipline to consult the vault *before* answering, not after Matt pushes back.

## Why this exists

Claude's #1 anti-pattern on this project ([[synthesis/claude-anti-patterns]]) is answering from active context when the canonical answer is already written down. That drift shows up as:

- recommending off-stack infrastructure when the Supabase+Vercel rule is in CLAUDE.md
- building client code against an assumed auth contract when the real one is documented
- paraphrasing architecture from memory when the canonical white paper is in the vault

The cost is wasted time and eroded trust. This skill is the reminder to stop and look.

## When to run this

Before making a substantive claim about any of these, run the lookup first:

- OpenScaffold architecture, the seven-layer model, or infrastructure conventions
- Any specific app (OpenFirehouse, FireHazmat, OpenChiropractor, OpenSalon, OpenService, Limitless Stack Hub)
- The Limitless Stack (the seven-tool integrated system)
- Paperclip — its auth model, deployment options, or how the Hub integrates with it
- People — Dale, Matt, their roles, decisions they've made
- CLAUDE.md protocols, end-of-session checklists, or the NotebookLM session-start query
- Conventions: `lsh_` / `fs_` / `hs_` / `oc_` table prefixes, the seed-module pattern, the `@openscaffold/core` package shape
- Past decisions (why we picked X over Y) — these are logged in `wiki/log.md` or captured in synthesis pages

If the question sounds simple but touches any of the above, still do the lookup. The lookup is cheap; guessing is expensive.

## The lookup order

### 1. `wiki/index.md` — the catalog

Always start here. The index is the map of what exists. Read it, then open the specific page(s) that matter. Follow `[[wiki-links]]` to related pages.

Path: `/Users/matthewlavin/Claude code antigravity/obsidian /wiki/index.md`

### 2. Relevant wiki pages

Once the index points you to a page, read it in full. Wiki pages have a consistent shape: `## Summary`, `## Key facts`, `## Relationships`, `## Open questions`, `## Sources`. The "Sources" section tells you which raw documents back the claim.

Pages are grouped by type:

- `wiki/entities/` — people and orgs (Dale, Matt, Open Scaffold Labs)
- `wiki/apps/` — one page per app in the ecosystem
- `wiki/concepts/` — patterns, protocols, primitives, terminology
- `wiki/sources/` — summaries of each raw document ingested
- `wiki/synthesis/` — filed answers, architecture diagrams, lint reports
- `wiki/overview.md` — top-level synthesis
- `wiki/log.md` — append-only activity log (query recent decisions here)

### 3. Pinecone semantic search — when the wiki is thin

If the wiki page doesn't cover the question, run:

```bash
cd "/Users/matthewlavin/Claude code antigravity/obsidian " && \
  python3.11 tools/pinecone-search.py "the question here" --top 5
```

By default it searches all three namespaces (`repos`, `wiki`, `uploads`) and merges by score. Narrow with flags when useful:

- `--namespace wiki` — only curated wiki pages
- `--namespace repos` — only source code and repo docs
- `--repo OpenFirehouse` — only this repo
- `--top 3` — fewer hits when you want the strongest signal

Cite the top hits in your answer (`<repo>/<path>` or `wiki/<path>`) so Matt can verify and so the answer can be filed back into the wiki.

**Known limit**: Matt's Pinecone account hits a monthly embedding-token ceiling on the `multilingual-e5-large` model. If searches return 429 `RESOURCE_EXHAUSTED`, skip this step and fall through to NotebookLM. Don't burn time debugging — it's a billing quota, not a bug.

### 4. NotebookLM — curated deep research

For questions that need synthesis across a curated source set rather than a single vector hit, query the relevant notebook via the `notebooklm` CLI:

```bash
notebooklm use <notebook-id> && notebooklm ask "..."
```

Notebook inventory is in `wiki/concepts/notebooklm-workflow.md`. The ones that matter most:

- `ab4b7ccb` — **Limitless Stack Hub** — Claude's reminder layer (anti-patterns, Hub page, CLAUDE.md, Hub repo CLAUDE.md, limitless-stack concept, paperclip concept). Query this at the start of any session that touches Hub or protocol work.
- `cdaa7a43` — **OpenScaffold Wiki** — every wiki page mirrored. Query when a question spans the full vault.
- `733f98ef` — **OpenScaffold Architecture** — 27 architecture docs + per-repo CLAUDE.mds.
- `1a0a0c47` — **OpenScaffold Business** — 29 business docs + 72 white papers.
- `9c8f3df0` — **OpenFirehouse Project Docs** — rules, recent changes, mistakes to avoid for OpenFirehouse/FireHazmat.
- `9830f04f` — **ERG Research** — ERG 2024 orange-page guide text.

The two access paths (Chrome MCP or `notebooklm-py` CLI) are documented in `wiki/concepts/notebooklm-workflow.md`.

### 5. Only now: reason from active context

If after all three lookups the answer isn't grounded, say so plainly. "The vault doesn't cover this; here's my best guess based on [reasoning]." Then offer to file the answer back into the wiki as `wiki/synthesis/<slug>.md` once Matt confirms it.

## What to cite

Every substantive claim should cite either a wiki page (by `[[link]]`), a raw source (`<repo>/<path>`), or a NotebookLM notebook. If a claim can't be cited from any of the four, it's a guess — flag it as such.

## What the output looks like

A good lookup-grounded answer reads like this:

> Paperclip's auth model is **Better Auth cookies for board operators, short-lived JWTs for agents** — there's no static bearer token for the board-operator endpoints. See [[concepts/paperclip]] and `paperclipai/paperclip/docs/api/authentication.md`. This is why the Hub's proxy (`limitless-stack-hub/server/src/paperclip.js`) needs a `HUB_TOKEN` middleware patch before it works against a stock Paperclip — the static-bearer assumption it was built against isn't accurate.

A bad lookup-skipped answer reads like this:

> Paperclip probably uses API keys — I'd recommend deploying with a bearer token for the Hub to use.

## End-of-session hook

When you file a substantive answer back into the wiki (step 5), run:

```bash
cd "/Users/matthewlavin/Claude code antigravity/obsidian " && \
  python3.11 tools/pinecone-sync.py --changed-only
```

so the Pinecone wiki namespace stays fresh for next session's lookups.

## Relationships

- Complements [[synthesis/claude-anti-patterns]] — this skill is the enforcement mechanism for anti-patterns #1, #2, and #3.
- Encodes the four-tool-lookup rule from the vault's [[CLAUDE.md]].
- Works alongside the session-start NotebookLM query against notebook `ab4b7ccb`.
