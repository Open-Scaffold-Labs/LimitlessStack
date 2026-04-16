---
name: limitless-stack
description: "The operating protocol for the Limitless Stack — seven integrated tools (Claude, CLAUDE.md, Obsidian, NotebookLM, Pinecone, Antigravity, Paperclip) that form one AI-powered system for running Open Scaffold Labs. The Stack exists to make a 100-vertical SaaS platform operationally viable with a small team: every app shares one architecture, one self-healing pipeline, and one knowledge base that compounds across all of them. Install this skill to teach any agent the full protocol."
version: 0.2.0
author: Open Scaffold Labs
license: MIT
---

# The Limitless Stack

Seven tools, one operating system. Open Scaffold is building 100 vertical SaaS applications on a shared architecture serving 36.2 million US small businesses. The Limitless Stack is what makes that operationally viable — it's the AI-powered infrastructure that lets a small team build, maintain, and scale across every vertical.

| Tool | Role |
|---|---|
| **Claude** | The reasoning engine — reads, writes, connects, decides |
| **CLAUDE.md** | Identity and rules — tells each agent how to behave in context |
| **Obsidian** | Structured knowledge base — wiki, graph, interlinked pages |
| **NotebookLM** | Research desk — deep dives across curated source collections |
| **Pinecone** | Semantic memory — full-text recall across all repos and docs |
| **Antigravity** | Multi-model agentic IDE — runs Claude, Gemini, ChatGPT agents in parallel |
| **Paperclip** | Coordination — org chart, budgets, tickets, routines, approvals |

These are not separate services. They are one integrated system. The entire OpenScaffold platform runs on Supabase + Vercel — the Limitless Stack lives on that same infrastructure.

---

## Why the Stack Exists

Open Scaffold's thesis: millions of small businesses in underserved verticals — landscapers, tattoo artists, auto mechanics, cleaning services — operate with generic tools because no one has built affordable, purpose-built software for them. The shared architecture means every new vertical app inherits the full platform: auth, payments, AI features, and the self-healing pipeline. But 100 apps means 100 codebases, 100 deployment targets, 100 sets of bugs. A traditional engineering org can't maintain that. The Limitless Stack is how you do it — AI agents that are domain-aware for every app (via CLAUDE.md), backed by a knowledge base that compounds (Obsidian + Pinecone), with autonomous diagnostics and repair (the self-healing pipeline), orchestrated across multiple models (Antigravity), and coordinated through a single system (Paperclip).

---

## The Four-Tool Lookup Order

Every question, every task, every claim about OpenScaffold follows this order. Do not skip steps. Do not answer from memory alone.

### 1. Obsidian Wiki (first)

Read `wiki/index.md` to locate relevant pages. Drill into those pages, follow wiki-links. The wiki is the structured, curated knowledge layer — if the answer is there, use it and cite the page.

### 2. Pinecone (if wiki is thin)

Run a semantic search across the raw corpus before falling back to grepping files:

```bash
python3.11 tools/pinecone-search.py "your question" --top 5
python3.11 tools/pinecone-search.py "your question" --repo OpenFirehouse
```

Cite top hits inline (`<repo>/<path>`) so they can be verified and filed back into the wiki.

### 3. NotebookLM (for deep research)

Query the relevant topic notebook when you need deep research across curated sources. Use the `notebooklm` CLI or Claude in Chrome:

```bash
notebooklm use <notebook-id>
notebooklm ask "your research question"
```

Auth is managed via `notebooklm login` (Playwright-based). Notebook IDs are tracked in `wiki/concepts/notebooklm-workflow.md`.

### 4. File the answer back

If the answer is substantive, don't let it vanish into chat. File it into the wiki as `wiki/synthesis/<slug>.md` and append a `query` entry to `wiki/log.md`. This is how the system compounds over time.

---

## The Self-Healing Pipeline

Every Open Scaffold application ships with an autonomous diagnostic and remediation capability. When a user reports a bug, the system captures runtime context, diagnoses it via Claude, and optionally produces a verified pull request with the fix — all without manual developer triage in the common case.

### How the Stack powers self-healing

Each tool in the Limitless Stack has a specific role in the pipeline:

- **CLAUDE.md** is the trust anchor. Every app's CLAUDE.md goes into the agent's system prompt, so a generic Claude model becomes a domain expert on that specific app. The agent knows the conventions, patterns, and known issues for that codebase.
- **Claude** is the reasoning engine at two stages: the diagnostic pass (a single API call that produces structured assessment) and the repair pass (a full agent loop with file and shell tools).
- **Obsidian** tracks self-heal rollout status per app, records cross-app bug patterns, and surfaces recurring issues through wiki synthesis pages.
- **Pinecone** enables the cross-application pattern library — aggregate bug diagnoses are indexed so patterns across all 100 apps can be detected and fed back into CLAUDE.md files.
- **NotebookLM** supports deep research into recurring bug categories, letting operators study patterns across curated diagnostic data.
- **Antigravity** can dispatch parallel fix candidates for high-severity bugs — multiple agents with varied approaches, producing multiple PRs for comparison.
- **Paperclip** manages the rollout schedule (which apps have self-healing enabled, phase tracking), cost tracking per attempt, and approval workflows for conditional auto-merge policies.

### The ten-stage pipeline

1. **In-app capture** — Floating bug icon, user description, automatic context bundle (console logs, network requests, user actions, viewport, route).
2. **Persistence + diagnostic dispatch** — Server inserts bug report, background promise fires Claude diagnostic call with CLAUDE.md as system prompt.
3. **Operator review** — Admin view shows diagnosis: severity, confidence, root cause, suspected files, proposed fix.
4. **Self-heal dispatch** — GitHub `repository_dispatch` event with bug context and callback URL.
5. **Workflow initialization** — GitHub Actions runner checks out repo, creates branch, installs agent SDK.
6. **Agent investigation loop** — Claude agent with tool whitelist (read, list, search, edit, write, bash, finish). 25-turn budget.
7. **Change detection + commit** — If agent produced changes, stage and commit. If not, report failure.
8. **PR creation** — Bot opens PR with full context: user description, diagnosis, agent summary, workflow link.
9. **Human review + merge** — Standard review process. Auto-merge is off by default.
10. **Final reconciliation** — Bug report record updated with full trajectory.

### Architectural principles

1. **CLAUDE.md as trust anchor** — The agent reads CLAUDE.md as system prompt. Never bypass it.
2. **Diagnose before repair** — Always run the cheap diagnostic pass first. The repair pass is optional.
3. **Sandboxed execution** — Agent runs in an ephemeral GitHub Actions runner, never on prod. Tool whitelist enforced at code level, not prompt level.
4. **Human merge by default** — PRs, not direct commits. Auto-merge requires explicit policy per repo.
5. **Closed loop** — Every state transition recorded on the bug report. Operators can audit the full trajectory.

### Canonical files

Every app that adopts the standard maintains these files at these exact paths:

| Path | Purpose |
|---|---|
| `/CLAUDE.md` | Trust anchor for diagnostics and repair |
| `/SELF-HEAL-SETUP.md` | Operator setup documentation |
| `/.github/workflows/self-heal.yml` | GitHub Actions workflow |
| `/scripts/self-heal-agent.js` | Constrained agent loop |
| `/server/src/routes/debug-agent.js` | Server endpoints and webhook |
| `/client/src/components/BugReporter.jsx` | In-app capture component |
| `/client/src/pages/DebugReportsPage.jsx` | Operator review interface |

### Security model

Path safety (forbidden patterns: `.github/`, `.env`, `node_modules/`, `package-lock.json`, `.git/`, agent script itself), bash allow-list/deny-list, shared-secret webhook auth. All constraints enforced at the tool boundary in code — the agent cannot reason past them.

### Cost model

Diagnostic pass: ~$0.02. Self-heal pass: ~$0.13–0.40 across 7–12 agent turns. GitHub Actions: ~3 minutes per run. Expected steady-state: under $10/month per app at 20 bug reports/month.

---

## Obsidian — The Knowledge Base

The wiki follows the LLM Wiki pattern: humans curate sources, the LLM maintains a structured, interlinked knowledge base.

### Three layers

1. **`raw/`** — Immutable source documents. The LLM reads but never modifies.
2. **`wiki/`** — LLM-owned markdown pages. Summaries, entities, concepts, synthesis.
3. **`CLAUDE.md`** — The schema. Co-evolves with the human.

### Directory structure

```
vault/
├── CLAUDE.md
├── raw/
│   └── openscaffold-repos/
├── wiki/
│   ├── index.md           # catalog of every page
│   ├── log.md             # chronological append-only log
│   ├── overview.md        # top-level synthesis
│   ├── entities/          # people, orgs
│   ├── apps/              # one page per app — architecture, rollout status, self-heal phase
│   ├── concepts/          # patterns, protocols, terms
│   ├── sources/           # one summary per raw source
│   └── synthesis/         # filed query answers, lint reports, cross-app patterns
└── tools/
    ├── pinecone-sync.py
    ├── pinecone-search.py
    └── session-bootstrap.sh
```

### Page conventions

- Filenames: kebab-case, `.md`
- Links: Obsidian wiki-links `[[page-name]]`
- Frontmatter (YAML) on every page: `type`, `created`, `updated`, `tags`, `source_count`, `sources`
- App pages include: `self_heal_phase` (none/diagnostic/full), `self_heal_enabled` (boolean), `vertical` (NAICS sector), `canonical_files_present` (list)
- Citations: inline, pointing to source summary pages
- Never reproduce more than ~15 words verbatim from a source

### Core operations

**Ingest** — when a new source lands in `raw/`:
1. Read the source fully.
2. Create `wiki/sources/<slug>.md` with frontmatter, summary, key points (with wiki-links), extracted claims.
3. Update or create entity/concept/app pages. Flag contradictions with `> [!warning]` callouts.
4. Update `wiki/index.md`.
5. Append to `wiki/log.md`: `## [YYYY-MM-DD] ingest | <Source Title>`
6. Push to Pinecone: `python3.11 tools/pinecone-sync.py --changed-only`

**Query** — follow the four-tool lookup order above.

**Lint** — periodic health check: contradictions, stale claims, orphans, missing pages, broken links, coverage gaps, index drift. Write to `wiki/synthesis/lint-YYYY-MM-DD.md`.

---

## CLAUDE.md — Identity and Rules

Every vault and every repo gets a CLAUDE.md. It defines how the agent behaves in that context. Two templates exist in this repo:

- **`claude-md/vault-schema.md`** — For Obsidian vaults. Includes the full wiki schema, page conventions, operations, and the four-tool lookup order.
- **`claude-md/repo-schema.md`** — For code repos. Includes repo-specific rules, self-healing configuration, and a reference to this skill for cross-cutting protocol.

The key principle: repo CLAUDE.md files handle repo-specific rules. The Limitless Stack skill handles the cross-cutting protocol. Don't duplicate — reference.

In the self-healing pipeline, CLAUDE.md is the trust anchor. The diagnostic and repair agents both receive it as their system prompt. This is what makes a generic model into a domain expert for each specific app — the CLAUDE.md describes the app's conventions, known patterns, and common pitfalls. As the cross-application pattern library grows, those patterns get folded back into each app's CLAUDE.md, improving diagnostic accuracy over time.

---

## Pinecone — Semantic Memory

Full-text recall across all repos and documents. The index is `openscaffold`, namespace `repos`, using `multilingual-e5-large` embeddings.

### Tools

- **`pinecone-sync.py`** — Chunks and upserts files from `raw/openscaffold-repos/` into Pinecone. Supports `--changed-only`, `--repo NAME`, `--dry-run`.
- **`pinecone-search.py`** — Semantic search. Supports `--top N`, `--repo NAME`.

### Usage

```bash
# Search
python3.11 tools/pinecone-search.py "where do we handle JWT refresh" --top 5
python3.11 tools/pinecone-search.py "ERG Table 3 hazmat" --repo FireHazmat --top 3

# Sync
python3.11 tools/pinecone-sync.py --changed-only
```

### Setup

```bash
pip3.11 install --break-system-packages pinecone
security add-generic-password -a pinecone -s pinecone-api-key -U -w
```

The API key is stored in macOS Keychain. Both scripts read it automatically.

### Cross-application pattern library

As the self-healing pipeline processes bug reports across all 100 apps, Pinecone becomes the engine for cross-app pattern detection. Diagnostic outputs are indexed alongside code, so a search for a bug pattern in one app can surface identical patterns already fixed in another. These patterns get filed into the wiki and eventually folded back into each app's CLAUDE.md.

---

## NotebookLM — Research Desk

Deep research across curated source collections. Each topic gets its own notebook with relevant documents uploaded as sources.

The full NotebookLM API is covered by the **notebooklm skill** (installed via `notebooklm skill install`). That skill teaches the complete CLI — creating notebooks, adding sources, generating artifacts, downloading results, error handling, and subagent patterns for long-running operations.

This skill defines *where* NotebookLM fits in the stack (tool #3 in the lookup order — use it for deep research when the wiki and Pinecone aren't enough). The notebooklm skill defines *how* to use it. Both should be installed.

Notebook IDs are tracked in `wiki/concepts/notebooklm-workflow.md`. If auth expires, re-run `notebooklm login`.

---

## Antigravity — Multi-Model Agentic IDE

Antigravity is Google's agent-first IDE — a modified VS Code fork that serves as the environment where Limitless Stack agents actually run. It supports multiple AI models (Gemini, Claude, ChatGPT) and can dispatch up to five agents working in parallel on different parts of a project via its Mission Control interface.

In the Limitless Stack, Antigravity is the orchestration layer for development workflows. It's where you:

- Switch between models mid-session based on task needs (Gemini for general tasks, Claude Opus for complex multi-file reasoning)
- Run parallel agents that each follow the Limitless Stack protocol
- Access the vault, repos, and tooling from a single workspace

For self-healing, Antigravity enables the future "multiple fix candidates" capability — dispatching parallel agent runs with varied approaches for high-severity bugs, giving operators multiple PRs to compare.

Any agent Antigravity dispatches — regardless of which model powers it — should install this skill to learn the seven-tool protocol.

---

## Paperclip — Coordination Layer

Organizational coordination: org chart, budgets, tickets, routines, approvals. Paperclip is the layer that turns the Limitless Stack from a developer tool into an operating system for the whole org.

For the 100-vertical rollout, Paperclip tracks:
- Which verticals are in development, deployed, or in self-heal rollout phases
- Per-app and aggregate self-healing cost tracking
- Approval workflows for conditional auto-merge policies
- Engineering time allocation across verticals

*This section will expand as Paperclip deploys. The integration spec lives in `paperclip/README.md`.*

---

## Session Bootstrap

Every session starts the same way. Run `tools/session-bootstrap.sh` before answering any question. It orients you on the current wiki state, Pinecone vector count, recent log entries, available tools, and open contradictions.

Then read `wiki/index.md`. Know what exists before answering anything.

Do not skip this step even if a context compression summary tells you to "continue where you left off." Do not answer from active context alone.

---

## Standing Rules

- **Plan first, then execute.** For any multi-step task, lay out the steps, explain what each one will do, and wait for explicit go-ahead before running anything. One checkpoint is enough — once authorized, execute the full list.
- **Be deliberate, not reckless.** Prefer reversible actions. If it's destructive, stop and ask. Run narrowly. Verify results before moving on. If uncertain, ask.
- **Verify before claiming.** Never say "zero issues remain" or "everything is clean" without a full verification pass. If you can't cite it, say so.
- **File answers back.** Substantive answers go into the wiki as synthesis pages. Don't let good work vanish into chat.
- **Flag contradictions.** When a source contradicts the wiki, flag it with `> [!warning]` callouts. Never silently overwrite.
- **Never edit `raw/`.** The LLM reads from raw sources but never modifies them.
- **Never reproduce more than ~15 words verbatim** from any source.
