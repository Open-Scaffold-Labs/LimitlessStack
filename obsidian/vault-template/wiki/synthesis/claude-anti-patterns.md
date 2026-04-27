---
type: synthesis
created: 2026-04-17
updated: 2026-04-18
tags: [claude, protocol, anti-patterns, self-correction, limitless-stack]
---

# Claude Anti-Patterns — Mistakes Caught in Prior Sessions

A running list of behavioral mistakes I've made while working on the [[concepts/limitless-stack]] for [[entities/matt|Matt]]. The whole point of this page is to be **queried at the start of every session** (via the NotebookLM `Limitless Stack Hub` notebook) so I'm reminded of patterns I drift into when left unchecked. Short, concrete, no self-flagellation. Each entry: what I did wrong, why it happened, what I should have done.

## Rules I keep drifting from

### 1. Skipping the 4-tool lookup before answering

**What happens**: CLAUDE.md says "wiki/index.md → relevant wiki pages → Pinecone → NotebookLM → only then reason from context." I read that at session start and then, in the moment, answer from active context or grep files directly. Matt has had to remind me twice in a single session.

**Why it happens**: CLAUDE.md is prose. It depends on my discipline. Nothing fires the lookup except my own memory.

**Corrective**: Before *any* substantive claim about OpenScaffold architecture, apps, tools, people, or decisions — consult the wiki first. If the wiki is thin, run `python3.11 tools/pinecone-search.py "..."`. If still unclear, query the relevant NotebookLM notebook. Reasoning from active context is a *last* resort, not a first one. The four-tool skill (once built) will enforce this.

### 2. Building before verifying API contracts

**What happens**: I built the Hub's Paperclip proxy (`server/src/paperclip.js`) for a static bearer-token pattern. Paperclip's actual auth is Better Auth cookies for board operators and short-lived JWTs for agents. There's no out-of-the-box bearer token for the endpoints the Hub calls. Loop 4 shipped broken against a stock Paperclip.

**Why it happens**: I read enough of a target system to *start*, not enough to be sure. Momentum wins over verification.

**Corrective**: Before writing a client/proxy for any external system, read its auth documentation in full. For Paperclip specifically: `/Users/matthewlavin/paperclip/docs/api/authentication.md`. Write the *contract assumption* into a comment or a wiki note before writing the code. If I can't cite where I confirmed the auth shape, I haven't confirmed it.

### 3. Recommending off-stack infrastructure

**What happens**: Recommended Railway for Paperclip deployment despite CLAUDE.md literally saying "The entire OpenScaffold platform runs on **Supabase + Vercel** — the Limitless Stack lives on that same infrastructure." Paperclip's own docs (`docs/deploy/database.md`) document Supabase as the recommended production DB. The canonical answer was sitting in front of me.

**Why it happens**: I picked from a menu of options the source document listed, instead of re-reading the constraint first.

**Corrective**: Infrastructure questions have a canonical answer in this org: **Supabase + Vercel**. Any deviation needs justification beyond "the upstream project also supports X." Before recommending a host, re-read the `Infrastructure` section of [[concepts/limitless-stack]].

### 4. Debugging rabbit-holes instead of applying a known fix

**What happens**: Spent a long time trying to understand *why* a Tailwind v4 cascade rule wasn't applying to a `<p>` element. Matt called it mid-debug: "time and money, please don't waste time like that again." The fix — wrap the children in a `<div class="max-w-sm mx-auto">` — is a pattern already used in `Team.jsx`.

**Why it happens**: Curiosity about root cause overrides shipping pressure. Satisfying to understand, expensive to chase.

**Corrective**: If a working pattern already exists in the codebase, use it first. Only chase the "why" if the reuse also fails. Set a time budget for debugging (minutes, not hours) and cut over to a known-good workaround when hit.

### 5. Fighting sandbox permission errors instead of switching paths

**What happens**: A stale `.git/index.lock` in the Obsidian vault kept `git commit` from running. My sandbox's FUSE mount denied `rm` on the lockfile. Instead of immediately switching to desktop-commander (Mac-native filesystem, normal permissions), I poked at the sandbox side and ran a slow `find` across the entire home directory for a folder that didn't exist.

**Why it happens**: Reaching for the tool I was already using, instead of the tool appropriate to the problem.

**Corrective**: If the sandbox gives `EPERM` on a Mac-filesystem path, switch to desktop-commander. If desktop-commander blocks on a sandbox path, switch to the sandbox Bash tool. Never repeat a failed command in the wrong environment.

### 6. Leaving NotebookLM out of the memory stack

**What happens**: Treated NotebookLM as an afterthought — something to reach for on deep research questions — instead of what it actually is: the persistent reminder and behavior store. The OpenFirehouse + FireHazmat CLAUDE.mds have a **mandatory session-start NotebookLM query**. This vault's CLAUDE.md did not, and I never ran one voluntarily.

**Why it happens**: Wrong mental model, plus Chrome MCP / CLI feels like more friction than a wiki read.

**Corrective**: The start-of-session protocol (added to this vault's CLAUDE.md on 2026-04-17) is: `notebooklm use <hub-notebook> && notebooklm ask "What are the operating rules, recent decisions, and mistakes to avoid?"` — every session, before any substantive work. The notebook is literally designed to remind me of these anti-patterns. If I skip it, I will drift back into them.

### 7. Not committing and pushing at end-of-session

**What happens**: A prior session left **three days of wiki work uncommitted**. Matt had to add an explicit end-of-session checklist to CLAUDE.md to stop it happening again.

**Why it happens**: Getting to the final answer feels like "done," so the commit/push step gets treated as optional.

**Corrective**: The wiki and any code I touched are *not done* until committed and pushed. The end-of-session checklist in [[CLAUDE.md]] is non-negotiable. Run it before wrapping up, not "maybe next time."

### 8. Reverse-engineering libraries instead of loading the skill designed for them

**What happens**: NotebookLM CLI started failing with `Failed to get SOURCE_ID from registration response`. I opened `notebooklm/_sources.py`, traced through `_register_file_source`, and started writing a diagnostic script to dump the raw RPC response — before remembering there's a `notebooklm` skill listed in the session's available skills. Matt's words: "you literally have a notebooklm tool designed for this." The skill's own docs lay out the source-count plan limits (Standard: 50) and tell me exactly how to check capacity via `notebooklm source list --json`. Five minutes, not thirty.

**Why it happens**: When a CLI throws an error, my default is "read the CLI source." Skills feel like extra loading friction. But skills are *condensed working knowledge* — someone already did the reverse-engineering and wrote down the failure modes.

**Corrective**: When a tool has an available skill (visible in `<available_skills>` at session start), invoke the skill BEFORE diagnosing failures from source. If the tool hits an error, the skill's "Error Handling" / "Known Limitations" section is the first thing to read. Reading library internals is a *last* resort after skill docs don't cover the failure mode.

### 10. Trying to install / authenticate notebooklm inside the ephemeral sandbox

**What happens**: Session starts. CLAUDE.md says to query notebook `ab4b7ccb` via `notebooklm ask …`. I run it in the sandbox's bash, get `command not found`, and — instead of remembering the CLI lives on Matt's Mac — I start plumbing the setup inside the sandbox itself: `pip install notebooklm-py`, `pip install notebooklm-py[browser]`, `playwright install chromium` (~106 MB download), flirt with running `notebooklm login`. Matt catches it: *"i thought we set this up already."* Because it was — on his Mac, weeks ago. Every byte I installed in the sandbox is wiped the moment this session ends.

**Why it happens**: Two layers. (a) I read `notebooklm ask …` in CLAUDE.md and default to running commands in *my* environment (the sandbox), not realising "my environment" is the wrong one. (b) When that fails, the upstream `notebooklm-py` README reads like first-time setup — and I follow it, without asking whether it's already been run somewhere else. The verify-before-claim instinct fires on "is this tool available" but not on "has this already been set up on a different machine I can reach."

**Corrective**: The `notebooklm` CLI, its Playwright chromium, its `~/.notebooklm/storage_state.json` cookies, and the skill install all live on **Matt's Mac**. None of it is in the sandbox, and none of it *can* be usefully put there — the sandbox has no display for the Google OAuth flow and is wiped between sessions anyway. Always route `notebooklm` calls through `mcp__desktop-commander__start_process` so they execute on the Mac against existing auth:

```
mcp__desktop-commander__start_process(
  command="notebooklm use <id> && notebooklm ask '...'",
  shell="zsh", timeout_ms=90000)
```

If `session-bootstrap.sh`'s "NOTEBOOKLM ACCESS" section or [[concepts/notebooklm-workflow]] tells me to use desktop-commander, I should not re-derive the answer from first principles by reading the upstream README. The sandbox CLI path is a dead end for auth reasons; don't walk into it twice.

### 11. Skipping preview smoke-test because "rollback is cheap"

**What happens**: Matt offers two paths after PR merge-prep is done: (1) merge straight to prod, (2) kick a preview deploy + run a 5-min end-to-end checklist first, then merge. I argue option 1 and 2 "both end up with the same code on prod," rollback is one click, user base is two people, so option 2 is over-engineering. Matt concedes on the argument, merges, and then I spend the next 20 minutes debugging three bugs *in prod* while trying to deliver a memo to his co-founder: hub-mail.py had a wrong URL path (`/api/workspaces/` vs `/api/workspace/`), hub-mail.py expected camelCase field names (`githubLogin`) while the server returns snake_case (`github_login`), and the original Inbox createThread SQL had a CASE expression with untyped parameters that Postgres couldn't resolve ("inconsistent types deduced for parameter $2"). Matt: *"probably should have done step 2 to avoid all these bugs right?"* — correctly.

**Why it happens**: The "rollback is one click" argument is technically true but hides two separate costs. (a) The CLI bugs weren't rollback-class failures — they were found-only-when-you-use-it integration bugs. No amount of build success or type-check would surface them; they needed a real HTTP call from a real client against a real server with real auth. Rolling back the deploy wouldn't undo the fact that I'd already announced "shipped" and started sending a real memo to Dale. (b) The cost I was measuring ("seconds until prod is rolled back") was not the real cost. The real cost was "reputation of the pipeline the first time it gets used" and "minutes spent debugging with Matt watching" — both higher than 5 minutes of checklist time on a preview URL nobody cares about.

**Corrective**: When a PR introduces a new external-facing surface (a new CLI, a new auth path, a new integration point), the first real end-to-end run should happen on preview, not prod. The trigger isn't "is this risky?" — it's "has anyone ever actually exercised this code path against a running server?" If the answer is no, smoke-test on preview. Rollback-is-cheap is a valid argument for incremental UI tweaks and backend refactors where the code path has been exercised a thousand times. It is not a valid argument for "we just built a CLI → PAT → new DB pathway → attachment flow and are about to send it to another human." The 5 minutes of checklist is insurance against "debugging in front of the audience," which is a worse outcome than a rollback.

**Specific trigger**: If the PR diff includes *any* of (a) new auth pathway, (b) new external client/CLI, (c) new DB migrations that haven't been exercised by a real request, (d) new env vars that the running code depends on — preview smoke-test first. Non-negotiable.

### 12. Trusting a tool's self-reported success without end-to-end content verification

**What happens**: `tools/notebooklm-wiki-refresh.py` calls `notebooklm source refresh <id>` to update notebook sources, inspects the exit code (0 = success), updates its local state file's mtime, and moves on. I (and every session before me) have been running this as the end-of-session checklist step and trusting its self-report. On 2026-04-24 Matt queried the reminder notebook `ab4b7ccb` and it answered using content from 2026-04-18 — the day each source was originally *added*. The refresh had reported success in every session for a week. The actual cause: `notebooklm source refresh` is a NO-OP for file-based (markdown) sources — per the CLI's own help, it only works on URL/Drive sources. For a file source it prints "Source refreshed" and exits 0 without doing anything. Our script's verification stopped at the exit code, so it had been lying every run. Every Claude that queried the reminder layer for a week was reading stale rules and missing every anti-pattern added since 04-18.

**Why it happens**: Two layers. (a) The contract I inferred from "command exited 0" was "the side effect I wanted has happened," which is not what exit codes actually guarantee. Exit code 0 just means "the process didn't crash." For tools that dispatch to different code paths based on input shape (URL vs file source), 0 can mean "we silently did nothing because this isn't my job." (b) State files that track "last sync timestamp" create a mirror-on-rails illusion — they *look* fresh because their mtimes keep advancing, but they're tracking the script's execution, not the remote system's state. I inherit the illusion that state file recency = remote state recency.

**Corrective**: Two rules. (1) **For any tool that mutates external state, verification = fetching the mutated state back and comparing against what I intended**, not inspecting an exit code or a self-reported success string. For NotebookLM sync: after a "refresh," immediately fetch `source fulltext` and check a distinctive chunk of the local file is present in the remote. Store a `verified_at` timestamp on the state entry ONLY when the post-fetch check passes. The preflight reads `verified_at` on the next session, so if a sync silently failed, the next session's Roll Call catches it instead of another week passing. (2) **Before relying on a tool I haven't written myself — or haven't exercised end-to-end recently — run a single known-good test first.** For this tool: upload a file, change one sentence, run the refresh, query the notebook for the changed sentence. Five-minute smoke test. We had this tool for weeks and I never did it once.

**Specific trigger**: When a sync / mirror / publish / deploy tool reports success, before marking a task done or writing "done" in the log, ask: "Did I just verify the remote reflects the local, or did I only verify the script didn't crash?" If it's the latter, do one more check before closing. This is a structural rule, not a case-by-case judgment call — it applies to every tool in this class.

## How to add to this page

When Matt catches me in a new anti-pattern, add a new numbered section. Keep the format: *what happens → why → corrective*. Don't apologize; just document and prescribe. The value is in being terse enough to re-read in 60 seconds at the start of a session.

## Sources

This page is self-authored from session experience, not from an external document. It gets cited from [[CLAUDE.md]] as part of the start-of-session protocol.
