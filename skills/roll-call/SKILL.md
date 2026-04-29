---
name: roll-call
description: Session-start readiness check for the Limitless Stack. Run this FIRST in any session that touches the OpenScaffold / Limitless-Stack work — it mechanically verifies that all seven tools (Claude, CLAUDE.md, Obsidian, NotebookLM, Pinecone, Hub Workspace, Paperclip) are present, authenticated, and in sync before doing substantive work. Trigger any time the user greets you with "hey claude", asks you to pick up where you left off, hands off context from a previous session, references the Limitless Stack, or starts a new conversation on this vault. Also trigger if the user says "roll call", "preflight", "are you ready", "is everything connected", or similar. Do NOT begin substantive work (writing wiki pages, editing code, answering architecture questions, running ingests) until Roll Call returns READY or Matt explicitly greenlights proceeding with known drift.
---

# Roll Call — Limitless Stack Readiness Check

Every substantive session on this vault needs all seven tools of the [[concepts/limitless-stack]] working together. Roll Call is the mechanical gate that makes sure they are — *before* work starts, not after Matt notices something drifted.

## Why this exists

The #1 failure mode on this project (see [[synthesis/claude-anti-patterns]] entries #1, #6, #10) is answering from active context while one or more of the memory tools is silently stale. Examples:

- Pinecone hasn't been synced since the last wiki edit → semantic search misses recent pages.
- NotebookLM's `ab4b7ccb` reminder notebook hasn't been refreshed since CLAUDE.md changed → the "recent mistakes" query returns yesterday's rules.
- The vault has uncommitted changes from a prior session → Matt's GitHub copy drifts from the canonical.
- The `notebooklm` CLI's cookie jar has expired on Matt's Mac → every notebook query fails.

Reading the prose rules in CLAUDE.md relies on Claude's discipline. Roll Call replaces discipline with a script that *cannot* be forgotten once it's called.

## Project-aware dispatch

Roll Call runs `tools/limitless-preflight.sh` from **whichever vault is currently open** — the preflight is per-project, not global. Each project's preflight reads `.limitless-project.py` (the project manifest) at the vault root to determine which checks apply and what notebook IDs / Pinecone index / sync paths to use.

For the Hub vault (`/Users/matthewlavin/Claude code antigravity/obsidian`), check #5 specifics are: `notebooklm auth check --test` passes; `cdaa7a43` mirror fresh; `ab4b7ccb` reminder sources newer than the files they mirror. **Other projects (the-match, future verticals) will have their own notebook IDs declared in their manifests** — read each project's `.limitless-project.py` before assuming the Hub IDs apply.

To scaffold a new project that participates in Roll Call: run `/Users/matthewlavin/LimitlessStack/bin/limitless-stack-init <project_id> <target_path>`. That installs tools/, wiki/, CLAUDE.md, and a manifest skeleton.

## What Roll Call does

Runs `tools/limitless-preflight.sh` on Matt's Mac (via `mcp__desktop-commander__start_process`) and interprets the exit code.

The script checks each of the seven tools:

1. **Claude** — implicitly present (the script is running because Claude invoked it).
2. **CLAUDE.md** — exists and is readable.
3. **Obsidian** — `wiki/index.md` readable, page count sane, git clean (or count uncommitted files).
4. **Pinecone** — API key in Keychain, `describe_index_stats` works, last sync newer than the newest wiki edit.
5. **NotebookLM** — `notebooklm auth check --test` passes; `cdaa7a43` mirror fresh; `ab4b7ccb` reminder sources newer than the files they mirror.
6. **Hub Workspace** — not session-critical for Cowork agents (it's Matt's local IDE). Documented skip.
7. **Paperclip** — deployment in progress (task #38). Documented skip until deployed; script will add a real check then.

Exit codes:

- `0` — **READY**. All green. Proceed with the user's request.
- `1` — **WARN**. Yellow findings only. Report them briefly to Matt, then proceed unless Matt says otherwise.
- `2` — **BLOCK**. Red findings. Do NOT proceed with substantive work until fixed or Matt explicitly overrides.

## How to run

```
mcp__desktop-commander__start_process(
  command="bash '/Users/matthewlavin/Claude code antigravity/obsidian /tools/limitless-preflight.sh'",
  shell="zsh",
  timeout_ms=90000
)
```

The script is idempotent, read-only (except for calling `notebooklm auth check` which refreshes the token silently), and typically finishes in under 10 seconds.

## Interpreting the output

The script prints two blocks at the end: a **USAGE REMINDERS** section (behavioral routing contract — how to actually use each tool this session) and a green/yellow/red **verdict** with findings. Copy both into your first response to Matt so the state AND the routing rules are visible.

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
| Obsidian | `wiki/index.md` readable + git clean | Read via sandbox path; follow four-tool-lookup skill |
| Pinecone | API key in Keychain + index stats OK + sync fresh | `pinecone-search.py` via desktop-commander; never raw client in sandbox |
| NotebookLM | `auth check --test` passes + mirror + reminder sources fresh | `Skill(notebooklm)` + `mcp__desktop-commander__start_process`; never bare CLI in sandbox |
| CLAUDE.md | file readable | Read at session start; trust anchor |

Drift in either column — stale sync OR drifting routing — is a problem. Roll Call surfaces both.

## Self-improvement rule (important)

Roll Call is designed to **get better each session**. If during a session:

- A drift mode is discovered that the preflight didn't catch (e.g., a file got corrupted, an auth token silently expired, a repo got force-pushed), **add a new check to `tools/limitless-preflight.sh` before closing the session**.
- An existing check fires a false positive or false negative, **tune the threshold or logic before closing the session**.
- A new tool joins the Limitless Stack (e.g., Paperclip goes live), **add its check to the script**.

Also log the improvement:

- Append a `schema` entry to `wiki/log.md` describing what check was added/tuned and why.
- If the drift mode is behavioral (something Claude did wrong), add it to [[synthesis/claude-anti-patterns]] as a numbered entry.

This is the "self-learning" loop Matt specified: *"the limitless stack gets more powerful with each use."* The preflight script is the embodied memory; this skill is the reminder to feed it.

## When NOT to run Roll Call

Don't block trivial conversations on a full preflight. Skip Roll Call when:

- The user asks a pure conversational question with no tool use ("how are you?", "what's the capital of France?").
- The user's request is obviously about something outside the OpenScaffold / Limitless-Stack work (e.g., unrelated code help on a different repo).
- The user explicitly says "skip roll call" or "just do X".

For everything else — wiki questions, architecture questions, ingests, code edits on any Limitless-Stack repo, NotebookLM queries, Pinecone searches — run Roll Call first.

## Relationship to other skills

- **`four-tool-lookup`** — runs *after* Roll Call, per-question. Roll Call confirms the tools are up; four-tool-lookup is the discipline to actually use them in order.
- **`notebooklm`** — Roll Call's check #5 depends on `notebooklm auth check --test`. If that skill has been updated (new CLI version, new auth path), update the check in lockstep.
- **`verify-before-claim`** — Roll Call is an application of verify-before-claim at the tool-availability layer. Before asserting "NotebookLM isn't connected," run Roll Call and let the script verify.

## Sources

- `tools/limitless-preflight.sh` — the actual check script (lives in the Obsidian vault, runs on Matt's Mac).
- [[concepts/limitless-stack]] — the seven-tool vision this skill enforces.
- [[synthesis/claude-anti-patterns]] — the behavioral failure modes this skill exists to prevent.
- [[concepts/notebooklm-workflow]] — the desktop-commander routing pattern used in check #5.
