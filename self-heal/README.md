# Self-Healing Pipeline

The self-healing standard adds autonomous diagnostic and remediation capability to every vertical SaaS application in the Open Scaffold ecosystem. Users report bugs through an in-app interface; an AI agent pipeline diagnoses the issue and optionally produces a verified pull request — without manual developer triage in the common case.

## Why this exists

Open Scaffold is building 100 vertical applications on a shared architecture. Traditional engineering can't maintain 100 codebases. The self-healing pipeline compresses the time between a user reporting a bug and a fix being available for review from hours or days to minutes, at a marginal cost of ~$0.13 per attempt. This is what makes the 100-vertical model operationally viable.

## How each Limitless Stack tool serves the pipeline

| Tool | Role in Self-Healing |
|---|---|
| **CLAUDE.md** | Trust anchor — goes into the agent's system prompt so it becomes a domain expert on each specific app |
| **Claude** | Reasoning engine at both stages: diagnostic pass (single API call → structured assessment) and repair pass (agent loop with tools) |
| **Obsidian** | Tracks rollout status per app, records cross-app bug patterns, surfaces recurring issues as wiki synthesis pages |
| **Pinecone** | Powers the cross-application pattern library — indexed diagnoses surface patterns across all 100 apps |
| **NotebookLM** | Deep research into recurring bug categories across curated diagnostic data |
| **Antigravity** | Dispatches parallel fix candidates for high-severity bugs — multiple agents, multiple PRs for comparison |
| **Paperclip** | Manages rollout schedule, per-app cost tracking, approval workflows for auto-merge policies |

## The pipeline (ten stages)

1. **In-app capture** — User clicks bug icon, enters description. JavaScript module delivers context bundle: last 50 console messages, 50 network requests, 50 user actions, current route, viewport, user agent.
2. **Persistence + diagnostic dispatch** — Server persists the report, fires a Claude diagnostic call with the app's CLAUDE.md as system prompt. Returns structured JSON: severity, confidence, root cause, suspected files, proposed fix.
3. **Operator review** — Admin view shows full diagnosis. Operator can rediagnose, mark resolved, or trigger self-heal.
4. **Self-heal dispatch** — Server fires GitHub `repository_dispatch` with bug context, callback URL, and shared-secret token.
5. **Workflow initialization** — GitHub Actions runner checks out repo, creates branch (`self-heal/bug-N-runID`), installs Claude Agent SDK.
6. **Agent investigation loop** — Claude agent with tool whitelist (read, list, search, edit, write, bash, finish). 25-turn budget, 4K tokens per turn.
7. **Change detection + commit** — If changes exist, stage and commit. If not, fire failure callback.
8. **PR creation** — Bot opens PR with labels (`self-heal`, `bug`, `ai-generated`), full context in description.
9. **Human review + merge** — Standard review process. Auto-merge off by default.
10. **Final reconciliation** — Bug report updated with complete trajectory.

## Canonical files

Every app that adopts the standard maintains these at these exact paths:

| Path | Purpose | Template |
|---|---|---|
| `/CLAUDE.md` | Trust anchor for diagnostics and repair | `claude-md/repo-schema.md` |
| `/SELF-HEAL-SETUP.md` | Operator setup docs for secrets and config | `templates/SELF-HEAL-SETUP.md` |
| `/.github/workflows/self-heal.yml` | GitHub Actions workflow | `templates/self-heal.yml` |
| `/scripts/self-heal-agent.js` | Constrained agent loop with tool whitelist | `templates/self-heal-agent.js` |
| `/server/src/routes/debug-agent.js` | Server endpoints and webhook | App-specific |
| `/client/src/components/BugReporter.jsx` | In-app capture component | App-specific |
| `/client/src/pages/DebugReportsPage.jsx` | Operator review interface | App-specific |

Templates in this directory provide the canonical starting point. The server routes and client components are app-specific because they depend on the app's data model and UI framework, but the workflow and agent script are standardized.

## Security model

All safety constraints are enforced at the tool boundary in code — the agent cannot reason past them:

- **Path safety** — Normalized paths, no parent traversal, resolved against repo root, forbidden patterns (`.github/`, `.env`, `node_modules/`, `package-lock.json`, `.git/`, agent script itself)
- **Bash safety** — Allow-list (ls, cat, grep, find, head, tail, wc, npm test, npm run build, npx jest) + deny-list (rm, mv, sudo, curl, wget, chmod) + metacharacter check
- **Auth** — Shared-secret token on webhook callbacks, validated in constant time. No production secrets accessible to the agent.
- **Sandboxed execution** — Agent runs in ephemeral GitHub Actions runner with fresh checkout. No access to production databases, secrets, or infrastructure.

## Cost model

| Pass | Input tokens | Output tokens | Cost |
|---|---|---|---|
| Diagnostic | ~2,000 | ~700 | ~$0.02 |
| Self-heal | ~30,000 | ~5,000 | ~$0.13–0.40 |
| GitHub Actions | — | — | ~3 min/run |

Expected steady-state at 20 reports/month: under $10/month per app.

## Rollout phases

1. **Phase 1 — Diagnostic only** — Bug table, diagnostic endpoint, BugReporter component, admin page. No autonomous code modification. (OpenRestaurant: complete)
2. **Phase 2 — Self-heal pipeline** — Self-heal columns, dispatch + webhook endpoints, workflow + agent script, GitHub secrets. Opens PRs for human review.
3. **Phase 3 — Ecosystem rollout** — Standard ships to remaining apps. Expected order: OpenFirehouse, OpenInteriorDesign, ClearSightDental, then long tail.
4. **Phase 4 — Conditional auto-merge** — After 60+ days of Phase 3 across 3+ apps. Requires: high-confidence diagnostic, clean test run, ≤2 files touched. Off by default.

## Runtime compatibility

The canonical template uses UUID types (Supabase standard). For apps that also run locally with INTEGER user IDs, the `ensureBugReportsTable()` function should detect the column type at runtime by querying `information_schema.columns` and creating matching pk/fk types. OpenFirehouse implements this pattern (commit `aaef555`) — the same server code works against both local Postgres (INTEGER) and Supabase (UUID) without configuration.

## Future capabilities

- **Test-driven verification** — Agent must pass relevant tests before PR opens
- **Multiple fix candidates** — Parallel agent runs for high-severity bugs (via Antigravity)
- **Cross-application pattern library** — Aggregate diagnoses indexed in Pinecone, common patterns folded back into CLAUDE.md files (via Obsidian wiki)
