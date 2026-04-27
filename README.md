# Limitless Stack

Seven tools, one operating system for running Open Scaffold Labs.

Vertical SaaS has a scaling problem: every new market means new code, new bugs, new maintenance — and eventually more engineers than the business can support. The Limitless Stack is designed to break that constraint. It's an AI-powered operating protocol that lets a small team build, diagnose, and maintain applications across verticals without scaling headcount linearly. Self-healing pipelines handle bug repair autonomously. A shared knowledge base compounds every fix and architectural decision across the entire portfolio. Semantic memory surfaces patterns that no single engineer would catch.

The market opportunity is real — 36.2 million US small businesses across sectors where purpose-built software barely exists. The Limitless Stack is how Open Scaffold intends to reach them.

| Tool | Role |
|---|---|
| **Claude** | The reasoning engine |
| **CLAUDE.md** | Identity and rules — trust anchor for diagnostics and self-healing |
| **Obsidian** | Structured knowledge base — wiki, cross-app patterns, rollout tracking |
| **NotebookLM** | Research desk — deep dives across curated sources |
| **Pinecone** | Semantic memory — full-text recall across all repos |
| **Hub Workspace** | Multi-model agent runtime — Gemini default, Claude opt-in |
| **Paperclip** | Coordination — org chart, budgets, tickets, approvals |
## Install

**Option A: Claude Code Plugin (recommended)**

```
/plugin marketplace add Open-Scaffold-Labs/LimitlessStack
/plugin install limitless-stack@limitless-stack
```

**Option B: Manual**

```bash
git clone https://github.com/Open-Scaffold-Labs/LimitlessStack.git
cp -r LimitlessStack/skill/. ~/.claude/skills/limitless-stack/
```

## What's in the repo

### Skills (auto-installed by `install.sh` to `~/.claude/skills/`)

- **`skills/limitless-stack/`** — The installable protocol. Teaches any agent all seven tools, the four-tool lookup order, the **mandatory first action** (Roll Call → bootstrap → reminder query → wiki/index → four-tool lookup), the **end-of-session checklist** (8 steps: task files → commit/push → verify log → Pinecone → NotebookLM refresh → verify refresh landed → verify reminder bucket), the reminder bucket pattern, and the self-healing pipeline.
- **`skills/notebooklm/`** — The full NotebookLM API skill (bundled from notebooklm-py). Create notebooks, add sources, generate artifacts, download results.
- **`skills/four-tool-lookup/`** — The wiki → Pinecone → NotebookLM lookup discipline as its own skill, so the order is enforceable on top of the umbrella protocol.
- **`skills/roll-call/`** — Session-start preflight skill. Mechanically verifies all seven tools are present, authenticated, and in sync before substantive work starts. Returns READY / WARN / BLOCK.
- **`skills/verify-before-claim/`** — Enforces a verification protocol before declaring any tool, resource, or capability as "unavailable". Born from anti-pattern #12 — `notebooklm source refresh` reporting success while content stayed frozen for weeks.

### Operational tools (`tools/` — copied into your vault by `install.sh`)

- **`limitless-preflight.sh`** — the script Roll Call calls. Validates all seven tools, dedupe-checks every NotebookLM bucket, returns 0/1/2.
- **`session-bootstrap.sh`** — current-thesis snapshot at session start.
- **`notebooklm-wiki-refresh.py`** — routes wiki files into per-project + default + reminder NotebookLM buckets, uploads, and **verifies content actually landed**.
- **`notebooklm-dedupe.py`** — sweep any bucket for duplicate sources (uses cmd_replace correctly; the original wiki-refresh had a ghost-duplicate bug for two weeks before this was added).
- **`pinecone-sync.py`** — chunks the corpus, upserts into the `openscaffold` index, supports `--changed-only`, `--dry-run`, `--repo NAME`. Rate-limit aware.
- **`pinecone-search.py`** — semantic search across the index with optional `--repo` filter.

### Docs and templates

- **`claude-md/`** — CLAUDE.md templates for vaults and repos, including self-healing trust anchor configuration.
- **`obsidian/vault-template/`** — Vault skeleton with wiki structure ready to go. Includes a starter `wiki/synthesis/claude-anti-patterns.md` so new vaults inherit the institutional memory of mistakes worth not repeating.
- **`pinecone/`** — Reference copies of the sync + search scripts (the canonical source-of-truth lives in `tools/`).
- **`notebooklm/`** — Wiki refresh tooling for NotebookLM integration.
- **`self-heal/`** — Self-healing pipeline: canonical file templates (workflow, agent script, setup guide), security model, cost model, rollout plan.
- **`antigravity/`** — Integration spec for multi-model agent orchestration.
- **`paperclip/`** — Integration spec for organizational coordination.
- **`docs/setup-guide.md`** — Full setup walkthrough.
## The self-healing pipeline

Every Open Scaffold app ships with autonomous bug diagnosis and repair. Users report bugs in-app; a Claude agent pipeline diagnoses the issue and produces a verified PR — at ~$0.13 per attempt. The `self-heal/` directory contains the canonical templates for shipping this to any app:

- `self-heal/templates/self-heal.yml` — GitHub Actions workflow
- `self-heal/templates/self-heal-agent.js` — Constrained agent script with tool whitelist
- `self-heal/templates/SELF-HEAL-SETUP.md` — Operator setup guide

See `self-heal/README.md` for the full architecture, security model, and rollout plan.

## Full setup

See [`docs/setup-guide.md`](docs/setup-guide.md) for the complete walkthrough — accounts, dependencies, vault creation, Pinecone indexing, NotebookLM notebooks, and nightly sync scheduling.

## License

MIT