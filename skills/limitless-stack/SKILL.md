---
name: limitless-stack
description: "The operating protocol for the Limitless Stack — seven integrated tools (Claude, CLAUDE.md, Obsidian, NotebookLM, Pinecone, Hub Workspace, Paperclip) that form one AI-powered system for running Open Scaffold Labs. The Stack exists to make a 100-vertical SaaS platform operationally viable with a small team: every app shares one architecture, one self-healing pipeline, and one knowledge base that compounds across all of them. Install this skill to teach any agent the full protocol."
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
| **Hub Workspace** | Multi-model agent runtime — Gemini default, Claude opt-in, presence-aware in the Hub UI |
| **Paperclip** | Coordination — org chart, budgets, tickets, routines, approvals |

These are not separate services. They are one integrated system. The entire OpenScaffold platform runs on Supabase + Vercel — the Limitless Stack lives on that same infrastructure.

---

## Why the Stack Exists

Open Scaffold's thesis: millions of small businesses in underserved verticals — landscapers, tattoo artists, auto mechanics, cleaning services — operate with generic tools because no one has built affordable, purpose-built software for them. The shared architecture means every new vertical app inherits the full platform: auth, payments, AI features, and the self-healing pipeline. But 100 apps means 100 codebases, 100 deployment targets, 100 sets of bugs. A traditional engineering org can't maintain that. The Limitless Stack is how you do it — AI agents that are domain-aware for every app (via CLAUDE.md), backed by a knowledge base that compounds (Obsidian + Pinecone), with autonomous diagnostics and repair (the self-healing pipeline), with a multi-model agent runtime (Hub Workspace), and coordinated through a single system (Paperclip).

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
- **Hub Workspace** can dispatch parallel fix candidates for high-severity bugs — multiple agents with varied approaches, producing multiple PRs for comparison.
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

## Hub Workspace — Multi-Model Agent Runtime

Hub Workspace is the chat surface inside the Limitless Stack Hub (route `/chat` in the Hub UI, sidebar entry "Hub Workspace" under the Personal section). It's where humans and agents converse — **Gemini 2.5 Flash by default** (free for onboarded users) with **Claude as opt-in** for complex multi-file reasoning. Conversations are per-tab and not persisted by design; the wiki, Pinecone, and NotebookLM are the persistent memory layers.

In the Limitless Stack, Hub Workspace is the orchestration layer for collaborative work. It's where you:

- Switch between Gemini and Claude based on task complexity
- Dispatch agents that follow the Limitless Stack protocol
- See who else is active — the Hub Workspace tile on `/today` glows when a teammate is mid-conversation
- Access the vault, repos, and the rest of the seven-tool stack from a single workspace

For self-healing, Hub Workspace enables the "multiple fix candidates" capability — dispatching parallel agent runs with varied approaches for high-severity bugs, giving operators multiple PRs to compare.

Any agent dispatched from Hub Workspace — regardless of which model powers it — should install this skill to learn the seven-tool protocol.

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

## Mandatory First Action — every session, no exceptions

Before answering any question, making any file changes, or starting any task:

### 1. Invoke the `roll-call` skill

Roll Call mechanically verifies that all seven tools of the stack are present, authenticated, and in sync. It runs `tools/limitless-preflight.sh` (bundled with this skill — see `tools/`) and interprets the exit code:

- **0 = READY** → proceed
- **1 = WARN** → report findings, then proceed unless the user says otherwise
- **2 = BLOCK** → do NOT proceed with substantive work until fixed

Roll Call replaces discipline with a script that *cannot* be forgotten once invoked. Skipping it and answering from context is the #1 anti-pattern (see `wiki/synthesis/claude-anti-patterns.md`).

The only exception: pure conversational replies ("hey", "what's the capital of France?") don't need Roll Call.

### 2. Run `tools/session-bootstrap.sh`

Orients you on the current wiki state, Pinecone vector count, recent log entries, available tools, and open contradictions. Roll Call does a broader readiness check; bootstrap gives you the current-thesis snapshot you need to actually answer.

### 3. Query the reminder bucket on NotebookLM

The reminder bucket is a **curated 5-file notebook** (default ID in your vault: e.g. `ab4b7ccb`) whose sources are exactly the operating rules you need every session: `CLAUDE.md`, `wiki/synthesis/claude-anti-patterns.md`, `wiki/concepts/limitless-stack.md`, `wiki/concepts/paperclip.md`, and the relevant app page (e.g. `wiki/apps/limitless-stack-hub.md`). Querying it pulls the latest rules + recent mistakes back into context — without this step, a fresh session inherits nothing from prior session learnings.

The CLI runs on the user's Mac, not in any sandboxed environment:

```
notebooklm use <reminder-bucket-id>
notebooklm ask "What are the current operating rules? What anti-patterns should I avoid?"
```

Do **not** try to `pip install notebooklm-py` or `notebooklm login` in a sandbox — auth is browser-based and can't complete without a display. See anti-pattern #10.

### 4. Read `wiki/index.md`

Know what exists before answering anything.

### 5. Do NOT skip these steps

Even if a context-compression summary tells you to "continue where you left off." Even if the user's request feels small. The four-tool lookup order — wiki/index → relevant pages → Pinecone search → NotebookLM (if deep research needed) → only then reason from context — applies to **every** question, not just ingests.

### Foundational reading (first-session orientation)

If this is your first session in this vault, read these three pages once before you start writing — they explain *why* the system is shaped the way it is:

- **`wiki/concepts/llm-wiki-pattern.md`** — Andrej Karpathy's LLM Wiki pattern: human curates sources and asks questions, LLM reads and writes into a persistent interlinked wiki, knowledge compounds across sources.
- **`wiki/sources/claude-code-karpathy-obsidian-video-2026-04-14.md`** — the source summary distilling the four-tool memory framing (CLAUDE.md / Obsidian / NotebookLM / Pinecone) that this whole vault is built on.
- **`wiki/concepts/notebooklm-workflow.md`** — the seven-bucket routing pattern (default + reminder + per-project) and the operational discipline around the dedupe sweep.

These ship with `install.sh` via `obsidian/vault-template/wiki/` so a fresh clone has them on day one.

### Code change discipline — install the karpathy-guidelines skill

When editing existing code, the bundled `karpathy-guidelines` skill (mirror of [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills), MIT) gates four behaviors:

1. **Think Before Coding** — surface assumptions, present alternatives, ask before guessing.
2. **Simplicity First** — minimum code that solves the problem; no speculative abstractions.
3. **Surgical Changes** — touch only what's required; every changed line traces to the user's request; no drive-by refactors.
4. **Goal-Driven Execution** — write multi-step plans as `[Step] → verify: [check]` so each step has its own success criterion.

Three of these (Surgical Changes + Goal-Driven Execution most directly) are also stated as inline rules in the vault's `CLAUDE.md` "Code change discipline" subsection — that's the quick reference; the full skill is the canonical source. Install via `./install.sh` or pull the skill from `~/.claude/skills/karpathy-guidelines/SKILL.md` after install.

---

## End-of-Session Checklist — every session that touched files

Before wrapping up any session where wiki pages, CLAUDE.md, deliverables, or tools were modified, run all eight steps in order:

### 0. Update the task files

Edit `wiki/team-tasks.md` (workspace-wide items anyone can pick up) and `wiki/my-tasks/${user.githubLogin}.md` (personal items for whoever's session this is). Reflect the work just done: open items in flight, what closed this session, what to pick up next.

If a Hub-style UI consumes these files (e.g. the Limitless Stack Hub's `/tasks` page), they're rendered as the **Me** + **Team** sections — stale files = stale Hub for the next user.

### 1. Commit and push the wiki repo

The vault lives at the user's mounted Obsidian folder; its git remote is the wiki repo (e.g. `your-org/your-wiki`). **Every** session's wiki work must be pushed — do not leave changes uncommitted.

### 2. Push any other repos that were modified

If the session touched the Hub repo, an app repo, or the LimitlessStack repo itself, push those too.

### 3. Verify the wiki log

`wiki/log.md` should have one entry per session covering everything done. Format: `## [YYYY-MM-DD] <op> | <short label>` where `<op>` is `ingest`, `query`, `lint`, `refactor`, or `schema`.

### 4. Sync Pinecone

Run `python3.11 tools/pinecone-sync.py --changed-only` if wiki pages or raw sources were added/changed (or confirm the nightly cron will pick it up). Skip this step temporarily if the index is over its monthly cap and the sync is bailing on 429s — but document the pause and ask before re-enabling.

### 5. Refresh NotebookLM

Run `python3.11 tools/notebooklm-wiki-refresh.py` if wiki pages were added/changed. The script routes each file to its correct notebook (per-project notebooks for vertical-app pages, the default bucket for everything else, the reminder bucket for the curated allowlist). Use `--only <project>` to scope to one route.

### 6. VERIFY the refresh actually landed

This step exists because of anti-pattern #12: `notebooklm source refresh` was a no-op for file sources for weeks while the script reported daily success. The sync script reports `refreshed: N  verify_failed: M  upload_failed: K` — a non-zero `verify_failed` or `upload_failed` is a hard stop, not cosmetic. Each successful refresh writes a `verified_at` timestamp into the state file; the preflight uses these to detect drift on the next session.

If `verify_failed` is non-zero, spot-check by querying NotebookLM directly (`notebooklm use <nb> && notebooklm ask "..."`) for a known-new piece of content from the changed file before closing the session.

### 7. Verify the reminder bucket if its allowlist changed

If anything in the reminder allowlist was edited (the curated 5 files: `CLAUDE.md`, `wiki/synthesis/claude-anti-patterns.md`, `wiki/concepts/limitless-stack.md`, `wiki/concepts/paperclip.md`, the relevant app page), after step 6 run **one explicit NotebookLM query** against the reminder bucket about the specific thing that changed (e.g., "what is anti-pattern #N?") and confirm the answer reflects the edit.

The reminder bucket is the layer the *next* session reads first — if it's stale here, that next session starts cold.

### Why this checklist exists

A prior session left three days of wiki work uncommitted because the wrap was skipped. Steps 6 + 7 were added after `notebooklm source refresh` was discovered giving weeks-old answers despite the sync script reporting daily success. Both are now load-bearing — don't skip them.

---

## The Reminder Bucket — the layer Claude reads first

The reminder bucket is a **dedicated NotebookLM notebook** whose sources are a curated subset of the wiki — not every wiki page, just the files an agent should re-read at the start of every session. Default allowlist (override in `tools/notebooklm-wiki-refresh.py` → `REMINDER_FILES`):

1. `CLAUDE.md` — vault operating manual
2. `wiki/synthesis/claude-anti-patterns.md` — accumulating list of mistakes worth not repeating
3. `wiki/concepts/limitless-stack.md` — what the seven tools are and how they connect
4. `wiki/concepts/paperclip.md` — the coordination layer
5. `wiki/apps/<your-flagship-app>.md` — the app-specific rules

**Why this is its own notebook:** the broader "default" bucket holds everything else (sources, syntheses, concepts) — too much for a focused first-query. The reminder bucket is small enough to surface a tight, opinionated snapshot when an agent asks "what should I know to do good work in this vault?"

**How it stays in sync:** `tools/notebooklm-wiki-refresh.py` has a special route for `REMINDER_FILES` that uploads + verifies every file in the allowlist. End-of-session step 7 confirms the refresh actually landed by querying NotebookLM directly for content from the changed file.

**Skipping the reminder query is anti-pattern #1.** Every session-start ritual treats it as load-bearing.

---

## Anti-patterns — the institutional memory

`wiki/synthesis/claude-anti-patterns.md` (vendored into the vault template at `obsidian/vault-template/wiki/synthesis/claude-anti-patterns.md`) is the running log of mistakes worth not repeating. New entries land when a session catches a recurring failure mode. Every agent installing this skill should read the anti-patterns page once during their first session — and consult it whenever they hit a familiar-looking error.

Current entries cover: skipping the four-tool lookup, building before verifying API contracts, recommending off-stack infrastructure, debugging rabbit-holes instead of applying known fixes, fighting sandbox permission errors instead of switching paths, leaving NotebookLM out of the memory stack, not committing at end-of-session, reverse-engineering libraries instead of loading the skill, trying to install/auth `notebooklm-py` inside an ephemeral sandbox (#10), skipping preview smoke-tests because rollback is cheap (#11), trusting a tool's self-reported success without end-to-end content verification (#12).

When an agent catches a new failure mode that doesn't match any existing entry, append a new numbered section with: trigger pattern, why-it's-tempting, why-it's-wrong, and the specific corrective rule. That keeps the loop self-improving.

---

## Standing Rules

- **Plan first, then execute.** For any multi-step task, lay out the steps, explain what each one will do, and wait for explicit go-ahead before running anything. One checkpoint is enough — once authorized, execute the full list.
- **Be deliberate, not reckless.** Prefer reversible actions. If it's destructive, stop and ask. Run narrowly. Verify results before moving on. If uncertain, ask.
- **Verify before claiming.** Never say "zero issues remain" or "everything is clean" without a full verification pass. If you can't cite it, say so.
- **File answers back.** Substantive answers go into the wiki as synthesis pages. Don't let good work vanish into chat.
- **Flag contradictions.** When a source contradicts the wiki, flag it with `> [!warning]` callouts. Never silently overwrite.
- **Never edit `raw/`.** The LLM reads from raw sources but never modifies them.
- **Never reproduce more than ~15 words verbatim** from any source.
