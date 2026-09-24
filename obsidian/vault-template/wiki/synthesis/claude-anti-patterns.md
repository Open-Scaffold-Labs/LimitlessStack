---
type: synthesis
created: __TODAY__
updated: __TODAY__
anti_patterns_reviewed: __TODAY__   # the lesson-review ritual's date (Roll Call reads it) — not a page-edit date
tags: [meta, operations, lessons]
---

# Claude Anti-Patterns — mistakes not to repeat

This page is Claude's ledger of behavioural mistakes in THIS vault. It lives in the reminder
notebook, so every session reads it before substantive work. The twelve entries below are
**starter lessons** that came with the Limitless Stack; everything you add after them is your own.

Format for each entry: **Trigger** (the moment it happens) · **Why it's tempting** · **Rule**.
Numbers are permanent IDs — never renumber; add new entries at the end.

## Rules

### 1. Answering from memory instead of the lookup order
**Trigger:** a question that *feels* familiar. **Why it's tempting:** the answer seems obvious.
**Rule:** before any substantive claim, run the lookup order in CLAUDE.md (index → wiki → Pinecone →
NotebookLM) and cite what you found. If you can't cite it, say so.

### 2. Building against an API you haven't read
**Trigger:** writing a client or integration for an external system. **Why it's tempting:** the
common pattern usually works. **Rule:** read the system's auth and API docs in full first.

### 3. Recommending infrastructure outside the stack
**Trigger:** a deployment or hosting decision. **Why it's tempting:** another platform looks
simpler. **Rule:** check what CLAUDE.md says the stack runs on and recommend within it, unless
[YOUR NAME] asks for alternatives.

### 4. Rabbit-holing instead of applying the known fix
**Trigger:** a bug with a known workaround. **Why it's tempting:** understanding the root cause
feels thorough. **Rule:** apply the known fix first; investigate only if it fails or you're asked.

### 5. Fighting a permission error instead of switching environments
**Trigger:** "permission denied" or "not found" in one environment. **Why it's tempting:** one more
flag might work. **Rule:** one environment's "no" is not the answer — try the environment that has
the access (e.g. your own computer instead of a sandbox) before reporting it unavailable.

### 6. Treating NotebookLM as optional
**Trigger:** session start or end. **Why it's tempting:** the wiki is right there. **Rule:** the
reminder notebook is the first read and the refresh is part of every wrap-up.

### 7. Ending a session with work uncommitted
**Trigger:** wrapping up. **Why it's tempting:** "I'll push next time." **Rule:** run the
end-of-session checklist; nothing leaves the session uncommitted.

### 8. Reverse-engineering a library a skill already covers
**Trigger:** a CLI or library misbehaves. **Why it's tempting:** reading its source feels direct.
**Rule:** load the skill written for that tool first and follow its runbook.

### 9. Installing or signing in to a CLI inside a throwaway sandbox
**Trigger:** a tool isn't installed where Claude is running. **Why it's tempting:** `pip install`
is one line. **Rule:** tools that need your sign-in (like `notebooklm`) run on your own computer,
through a desktop bridge; a sandbox can't complete a browser sign-in and is wiped between sessions.

### 10. Skipping the preview check because rollback is cheap
**Trigger:** a change is ready to ship. **Why it's tempting:** "we can always roll back."
**Rule:** rollback undoes the deploy, not the damage; run the preview check first.

### 11. Trusting a tool's own success message
**Trigger:** a script prints success. **Why it's tempting:** exit code 0. **Rule:** verify the
result end to end — look at what actually landed, not at the receipt.

### 12. Mechanical checks without meaning checks
**Trigger:** every check is green. **Why it's tempting:** green feels like done. **Rule:** a check
can pass while measuring nothing; confirm it looked at real data (coverage, counts, content).

## How to add an entry

When a session catches a new recurring mistake, add `### 13. <short name>` at the end in the same
format. Don't apologise in the entry — describe the trigger and prescribe the rule.
