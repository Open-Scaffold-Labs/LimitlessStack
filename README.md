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

- **`skills/limitless-stack/SKILL.md`** — The installable protocol. Teaches any agent all seven tools, the four-tool lookup order, the self-healing pipeline, and how everything connects.
- **`skills/notebooklm/SKILL.md`** — The full NotebookLM API skill (bundled from notebooklm-py). Create notebooks, add sources, generate artifacts, download results.
- **`claude-md/`** — CLAUDE.md templates for vaults and repos, including self-healing trust anchor configuration.
- **`obsidian/vault-template/`** — Vault skeleton with wiki structure ready to go.
- **`pinecone/`** — Sync and search scripts for Pinecone semantic memory.
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