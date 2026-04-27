---
name: verify-before-claim
description: >
  Enforces a mandatory verification protocol before Claude declares any tool, resource,
  service, or capability as "unavailable", "unreachable", "not working", or "not accessible."
  This skill MUST be consulted any time Claude is about to tell the user that something
  cannot be done, is not connected, is offline, or is inaccessible. Also triggers when Claude
  encounters an error from one execution environment and is tempted to give up rather than
  trying alternatives. This includes: API failures, tool timeouts, file-not-found errors,
  network blocks, permission issues, missing packages, and any other access failure.
---

# Verify Before Claim

## Why this skill exists

Claude has a failure pattern: it hits one error in one execution environment, then tells the
user "X isn't available" without checking whether X is reachable through a different path.
This wastes the user's time, erodes trust, and is almost always wrong — because Claude
typically has multiple execution environments with different capabilities.

Real examples of this failure:
- Pinecone search failed from the sandbox (no API key in sandbox env) → but works perfectly
  when run on the user's Mac via Desktop Commander. Claude said "Pinecone unreachable" instead
  of trying the other path.
- Chrome extension wasn't connected → Claude said it couldn't open a URL, but Desktop
  Commander's `open` command works fine for that.- File bridge between sandbox and Mac seemed impossible → the shared workspace mount
  (Obsidian vault) was accessible from both sides the entire time.
- Said `gh` CLI wasn't available → didn't check whether Desktop Commander could run it
  on the Mac.

The root cause is laziness: Claude takes the first "no" as final instead of working the
problem. This skill exists to make that impossible.

## The Rule

**NEVER tell the user that something is unavailable, unreachable, broken, missing, or
inaccessible until you have tried EVERY execution environment in the checklist below.**

If you're about to type any of these phrases, STOP:
- "X isn't available"
- "X is unreachable"  
- "I don't have access to X"
- "X isn't connected"
- "I can't access X from here"
- "X isn't installed"
- "That tool/service isn't working"

Instead, work the checklist.

## The Checklist — Five Execution Environments

When something fails in one environment, try every other environment before giving up.
The order matters — start with the fastest/most direct path and work outward.
### 1. Sandbox (Cowork's isolated Linux environment)
- Has: Bash, Python, Node, pip, npm, file tools (Read/Write/Edit/Grep/Glob)
- Doesn't have: Mac Keychain secrets, GUI apps, Mac filesystem (except via workspace mount)
- Try this first for computation, file processing, and code execution

### 2. Workspace Mount (shared filesystem bridge)
- The mounted workspace folder is accessible from BOTH the sandbox AND the user's Mac
- Path in sandbox: `/sessions/*/mnt/<folder-name>/`
- Use this to bridge files between environments — write in sandbox, read from Mac (or vice versa)
- If you need to get a file from sandbox to Mac or Mac to sandbox, this is the bridge

### 3. Desktop Commander (runs directly on the user's Mac)
- Has: Full Mac filesystem, Keychain access, Homebrew packages, all CLI tools the user has installed
- Use `start_process` to run shell commands on the Mac
- Use `write_file` / `read_file` for Mac filesystem operations
- If something fails in the sandbox because of missing credentials, packages, or Mac-only
  tools — try it here BEFORE saying it's unavailable
- Can run: `gh`, `git`, `python3.11`, `pinecone-search.py`, `notebooklm`, and anything
  else installed on the Mac

### 4. Chrome MCP (browser automation)
- Has: DOM access, page navigation, form filling, tab management
- If Chrome MCP isn't connected, try Desktop Commander's `open` command as fallback for URLs
- Don't say "Chrome isn't available" — say "Chrome MCP isn't connected, but I can open
  that URL via Desktop Commander"
### 5. Computer Use MCP (native desktop control)
- Has: Screenshots, mouse/keyboard control for native Mac apps
- Use for apps that don't have a dedicated MCP
- Requires `request_access` before use

### 6. Ask the User (LAST RESORT ONLY)
- Only after environments 1-5 have been tried or ruled out with a specific reason
- When asking, explain what you tried and why it didn't work
- Suggest concrete next steps rather than just reporting failure

## How to Report When Something Actually Is Unavailable

After working the full checklist, if something genuinely cannot be done, report it like this:

"I tried X via [environment 1] and got [specific error]. Then I tried via [environment 2]
and got [specific result]. [Environment 3] can't help because [specific reason]. I've
exhausted my options — here's what I'd suggest as a next step: [concrete suggestion]."

NOT like this:
"X isn't available." ← This is never acceptable.

## Common Failure Patterns to Watch For

| Failure | Wrong response | Right response |
|---|---|---|
| Python package missing in sandbox | "Package not available" | Try `pip install` in sandbox, or check if it's installed on Mac via Desktop Commander |
| API key not in sandbox env | "API unreachable" | Run the API call on Mac via Desktop Commander where Keychain is accessible |
| Chrome MCP not connected | "Can't open that URL" | Use Desktop Commander `open` command, or `start_process` with `curl` |
| File only exists on Mac | "File not found" | Use Desktop Commander `read_file`, or copy via workspace mount |
| GitHub API blocked from sandbox | "Can't access GitHub" | Run `gh` commands on Mac via Desktop Commander |
| Tool not in deferred list | "Tool not available" | Run ToolSearch to check, tools may need to be fetched first |
## The Accountability Standard

This skill exists because of real failures that cost the user time and trust. The standard
is simple: if the user discovers within 30 seconds that something you said was unavailable
is actually available through a path you didn't try, that's a failure of this protocol.

Every "unavailable" claim should be something the user CANNOT easily disprove by pointing
at a tool you forgot to check. If they can, you didn't work the checklist.

## Summary

1. Something fails → don't report failure
2. Work the checklist: Sandbox → Workspace Mount → Desktop Commander → Chrome MCP → Computer Use → Ask User
3. Only after exhausting every path, report what you tried and suggest next steps
4. Never say "X isn't available" without receipts showing you checked every environment