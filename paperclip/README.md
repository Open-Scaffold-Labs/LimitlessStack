# Paperclip — Coordination Layer

Paperclip is the coordination layer — org chart, budgets, tickets, routines, approvals. It turns the Limitless Stack from a developer tool into an operating system for the whole org.

## Role in the Stack

Paperclip owns organizational state: who's responsible for what, what's budgeted, what's approved, what's due. For a 100-vertical platform, Paperclip is what keeps the business organized while the technical tools keep the code organized.

## Role in Self-Healing

Paperclip manages the operational and business side of the self-healing pipeline:

- **Rollout tracking** — Which of the 100 apps are in which self-heal phase (none → diagnostic → full). Tracks progress against the rollout plan: OpenRestaurant (Phase 1 complete), OpenFirehouse (next), then the rest.
- **Cost tracking** — Per-app and aggregate self-heal costs. Diagnostic pass (~$0.02/attempt) and repair pass (~$0.13–0.40/attempt) costs are recorded on bug reports and aggregated here.
- **Auto-merge approval workflow** — Phase 4 (conditional auto-merge) requires policy approval per repo. Paperclip manages these approvals: which repos are eligible, what conditions must be met (high-confidence diagnostic, clean tests, ≤2 files touched).
- **Engineering allocation** — With 100 verticals to build and maintain, Paperclip tracks where engineering time is going and helps prioritize based on market data (TAM analysis, vertical gap scores, software penetration rates).
- **Cost guardrails** — Per-user-per-day and global-per-day quotas for self-heal requests to prevent abuse. Paperclip enforces these budgets.

## Status

Deployment in progress. This spec will expand as Paperclip comes online.

## Integration points

- **Claude** — Paperclip delegates tasks to Claude for execution
- **CLAUDE.md** — Paperclip references CLAUDE.md rules when generating agent instructions
- **Obsidian** — Paperclip reads the wiki for context when making coordination decisions. App pages in the wiki reflect Paperclip's rollout status.
- **Pinecone** — Paperclip searches the corpus to inform ticket routing and prioritization
- **NotebookLM** — Paperclip queries notebooks for research backing decisions
- **Hub Workspace** — Paperclip hands off multi-agent tasks to Hub Workspace for orchestration
- **Self-healing** — Paperclip owns rollout scheduling, cost tracking, auto-merge approvals, and rate limiting
