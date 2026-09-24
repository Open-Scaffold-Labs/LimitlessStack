---
name: roll-call
description: Session-start readiness check for the Limitless Stack. Run this FIRST in any session that touches the OpenScaffold / Limitless-Stack work — it mechanically verifies that all seven tools (Claude, CLAUDE.md, Obsidian, NotebookLM, Pinecone, Hub Workspace, Paperclip) are present, authenticated, and in sync before doing substantive work. Trigger any time the user greets you with "hey claude", asks you to pick up where you left off, hands off context from a previous session, references the Limitless Stack, or starts a new conversation on this vault. Also trigger if the user says "roll call", "preflight", "are you ready", "is everything connected", or similar. Do NOT begin substantive work (writing wiki pages, editing code, answering architecture questions, running ingests) until Roll Call returns READY or the user explicitly greenlights proceeding with known drift.
---

# Roll Call — Limitless Stack Readiness Check

Every substantive session on this vault needs all seven tools of the [[concepts/limitless-stack]] working together. Roll Call is the mechanical gate that makes sure they are — *before* work starts, not after the user notices something drifted.

## Why this exists

The #1 failure mode (see [[synthesis/claude-anti-patterns]] — the lessons on skipping the lookup order, leaving NotebookLM out, and signing in to a CLI inside a sandbox) is answering from active context while one or more of the memory tools is silently stale. Examples:

- Pinecone hasn't been synced since the last wiki edit → semantic search misses recent pages.
- The reminder notebook hasn't been refreshed since CLAUDE.md changed → the "recent mistakes" query returns yesterday's rules.
- The vault has uncommitted changes from a prior session → the GitHub copy drifts from the local one.
- The `notebooklm` CLI's sign-in has expired on the user's computer → every notebook query fails.

Reading the prose rules in CLAUDE.md relies on Claude's discipline. Roll Call replaces discipline with a script that *cannot* be forgotten once it's called.

## Project-aware dispatch

Roll Call runs `tools/limitless-preflight.sh` from **whichever vault is currently open** — the preflight is per-project, not global. Each project's preflight reads `.limitless-project.py` (the project manifest) at the vault root to determine which checks apply and what notebook IDs / Pinecone index / sync paths to use.

Check #5 specifics come from that vault's manifest: `notebooklm auth check --test` passes; the default wiki notebook (`NOTEBOOKLM["default"]`) is fresh; the reminder notebook's (`NOTEBOOKLM["reminder"]["notebook_id"]`) sources are newer than the files they mirror. **Every vault declares its own notebook IDs** — read the open vault's `.limitless-project.py`; never assume another vault's IDs apply.

To scaffold a new project that participates in Roll Call: run `~/LimitlessStack/bin/limitless-stack-init <project_id> <target_path>` (if you cloned LimitlessStack somewhere else, use that path). That installs tools/, wiki/, CLAUDE.md, and a manifest skeleton.

## What Roll Call does

Runs `tools/limitless-preflight.sh` on the user's own computer (Claude Code's shell, or Desktop Commander's `start_process` from the Claude desktop app) and interprets the exit code. It must run where the user signed in to NotebookLM — never in a cloud sandbox.

The script checks each of the seven tools:

1. **Claude** — implicitly present (the script is running because Claude invoked it).
2. **CLAUDE.md** — exists and is readable.
3. **Obsidian** — `wiki/index.md` readable, page count sane, git clean (or count uncommitted files).
4. **Pinecone** — API key in Keychain, `describe_index_stats` works, last sync newer than the newest wiki edit.
5. **NotebookLM** — `notebooklm auth check --test` passes; the default wiki notebook is fresh; the reminder notebook's sources are newer than the files they mirror (IDs from the manifest).
6. **Hub Workspace** — optional; checked only when the manifest's `SERVICES` names a health URL.
7. **Paperclip** — optional; checked only when the manifest's `SERVICES` names a health URL.

**In a shared vault** (one with `.authors.json` and a `VAULT_OWNER` in the manifest), Roll Call is per person: whoever runs it sees only their own machine, their own sign-ins and their own task file (`wiki/my-tasks/<login>.md`). The vault's upkeep — tools kept in step with LimitlessStack, the nightly job, the lesson review, the shared task list, the notebooks' freshness and capacity, the Pinecone sync — appears only on the owner's Roll Call. A teammate's Roll Call also checks that their Google account can open every notebook the vault uses.

Exit codes:

- `0` — **READY**. All green. Proceed with the user's request.
- `1` — **WARN**. Yellow findings only. Report them briefly to the user, then proceed unless they say otherwise.
- `2` — **BLOCK**. Red findings. Do NOT proceed with substantive work until fixed or the user explicitly overrides.

## How to run

```
mcp__desktop-commander__start_process(
  command="bash '<vault>/tools/limitless-preflight.sh'",
  shell="zsh",
  timeout_ms=90000
)
```

`<vault>` is the folder that holds this vault's CLAUDE.md: the current directory for a terminal agent (Claude Code, Grok Build), or the connected folder's path on the computer in the Claude desktop app. Keep the quotes — a vault folder name can end in a space.

The script is idempotent, read-only (except for calling `notebooklm auth check` which refreshes the token silently), and typically finishes in about 25 seconds (measured 2026-09-24). If a run ever goes past the Claude desktop app's ~60-second tool-call limit, run it detached and read its output file.

## Interpreting the output

The script prints two blocks at the end: a **USAGE REMINDERS** section (behavioral routing contract — how to actually use each tool this session) and a green/yellow/red **verdict** with findings. Copy both into your first response to the user so the state AND the routing rules are visible.

Example output on a typical day:

```
  USAGE REMINDERS — how to actually use each tool this session

  • Obsidian wiki  → Read/Edit via sandbox path...
  • Pinecone       → python3.11 tools/pinecone-search.py via desktop-commander...
  • NotebookLM     → Invoke Skill(notebooklm) for ANY NotebookLM operation...
  • CLAUDE.md      → Read at session start...
  • End-of-session → commit + push, pinecone-sync, notebooklm refresh...

  green: 8   yellow: 1   red: 0
  ⚠ VERDICT: WARN — 1 drift finding(s)
```

**The USAGE REMINDERS are not optional.** Every tool interaction this session must match a pattern in that block. If you're about to call NotebookLM outside `Skill(notebooklm)` + `mcp__desktop-commander__start_process`, you're drifting — stop and route correctly. If you're about to query Pinecone from the sandbox with the pinecone Python client, you're drifting — use `pinecone-search.py` via desktop-commander instead.

### First-response templates

When you see WARN:

> Roll Call: WARN (1 yellow). Wiki has 3 uncommitted files. Everything else green. Following the USAGE REMINDERS for all tool use this session. Proceeding with your request; say the word if you want me to pause and handle the drift first.

When you see BLOCK:

> Roll Call: BLOCK (N red). [list findings]. I'm not proceeding with the substantive task until these are fixed. Want me to walk through the fixes, or do you have a reason to override?

When you see READY:

> Roll Call: READY. All seven tools green. Binding to USAGE REMINDERS for this session. Here's what I'll do: [answer / plan].

### The behavioral routing contract

Roll Call's USAGE REMINDERS block exists because "the tool is reachable" is not the same as "the tool will be used correctly." The preflight confirms readiness; the reminders bind each tool to the skill or invocation pattern that uses it correctly. Together they close the loop:

| Tool | Readiness check | Behavioral contract |
|---|---|---|
| Obsidian | `wiki/index.md` readable + git clean | Read via sandbox path; `tools/recall.sh <subject noun>` before asserting broken/missing/never-decided |
| Pinecone | API key in Keychain + index stats OK + sync fresh | `pinecone-search.py` via desktop-commander; never raw client in sandbox |
| NotebookLM | `auth check --test` passes + mirror + reminder sources fresh | `Skill(notebooklm)` + `mcp__desktop-commander__start_process`; never bare CLI in sandbox |
| CLAUDE.md | file readable | Read at session start; trust anchor |

Drift in either column — stale sync OR drifting routing — is a problem. Roll Call surfaces both.

## Deferred-blocker protocol (added 2026-06-10)

When Roll Call returns WARN/BLOCK and the user says "skip that" / proceeds anyway, the deferral is **one-time, not session-long**. The failure it prevents (see the lesson on caching a session-start failure as permanent): a NotebookLM BLOCK that was transient got reported as broken for a whole session.

1. **Make the blocker visible immediately** — create a task (TaskCreate) for it so it cannot fall out of awareness mid-session.
2. **Never re-assert the blocker from memory.** Before claiming the tool is still broken — in a status summary, a wrap-up, or an end-of-session step — re-run the relevant check (`notebooklm auth check --test`, the Pinecone probe, etc.). It's a 10-second command, and states recover: the 2026-06-10 NotebookLM BLOCK was transient, but Claude reported it broken for the whole session without re-checking.
3. **Repairing a tool routes through that tool's owning skill.** Fixing NotebookLM auth IS a NotebookLM operation → invoke Skill(notebooklm) first and follow its runbook. Same for any tool with an owning skill.
4. **Never silently skip end-of-session steps that depend on a deferred tool.** Re-check first; if genuinely still broken, list the skipped steps explicitly in the wrap-up so the user sees exactly what didn't happen.

## Self-improvement rule (important)

Roll Call is designed to **get better each session**. If during a session:

- A drift mode is discovered that the preflight didn't catch (e.g., a file got corrupted, an auth token silently expired, a repo got force-pushed), **add a new check to `tools/limitless-preflight.sh` before closing the session**.
- An existing check fires a false positive or false negative, **tune the threshold or logic before closing the session**.
- A new tool joins the Limitless Stack (e.g., Paperclip goes live), **add its check to the script**.

Also log the improvement:

- Append a `schema` entry to `wiki/log.md` describing what check was added/tuned and why.
- If the drift mode is behavioral (something Claude did wrong), add it to [[synthesis/claude-anti-patterns]] as a numbered entry.

This is the stack's self-learning loop: *it gets more powerful with each use.* The preflight script is the embodied memory; this skill is the reminder to feed it.

## When NOT to run Roll Call

Don't block trivial conversations on a full preflight. Skip Roll Call when:

- The user asks a pure conversational question with no tool use ("how are you?", "what's the capital of France?").
- The user's request is obviously about something outside the OpenScaffold / Limitless-Stack work (e.g., unrelated code help on a different repo).
- The user explicitly says "skip roll call" or "just do X".

For everything else — wiki questions, architecture questions, ingests, code edits on any Limitless-Stack repo, NotebookLM queries, Pinecone searches — run Roll Call first.

## Relationship to other skills

- **`audit-before-claim`** — runs *after* Roll Call, per-claim. Roll Call confirms the tools are up; `audit-before-claim` is the discipline for using them: `tools/recall.sh <subject noun>` before asserting broken/missing/never-decided, and the environment list before asserting "can't be done here". Roll Call is itself an application of that last rule at the tool-availability layer — before asserting "NotebookLM isn't connected," run Roll Call and let the script verify. (It absorbed the standalone `four-tool-lookup` and `verify-before-claim` skills on 2026-08-24; those had 2 and 0 lifetime invocations against this pair's 52 and 47.)
- **`notebooklm`** — Roll Call's check #5 depends on `notebooklm auth check --test`. If that skill has been updated (new CLI version, new auth path), update the check in lockstep.

## Sources

- `tools/limitless-preflight.sh` — the actual check script (lives in the vault, runs on the user's computer).
- [[concepts/limitless-stack]] — the seven-tool vision this skill enforces.
- [[synthesis/claude-anti-patterns]] — the behavioral failure modes this skill exists to prevent.
- [[concepts/notebooklm-workflow]] — the desktop-commander routing pattern used in check #5.
