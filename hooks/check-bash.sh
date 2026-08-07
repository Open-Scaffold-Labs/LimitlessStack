#!/bin/bash
# PreToolUse hook — deny known-wrong sandbox Bash commands.
# Matcher: Bash (configured in .claude/settings.json).
#
# Input (stdin JSON): tool_name, tool_input, tool_use_id
# Output on allow: exit 0, no stdout
# Output on deny: JSON to stdout with hookSpecificOutput.permissionDecision="deny"

INPUT=$(cat)

RESULT=$(INPUT_JSON="$INPUT" python3 - <<'PYEOF'
import os, json, sys, re

raw = os.environ.get("INPUT_JSON", "")
try:
    data = json.loads(raw) if raw else {}
except Exception:
    print("")
    sys.exit(0)

tool = data.get("tool_name", "")
cmd = data.get("tool_input", {}).get("command", "") or ""

if tool != "Bash":
    print("")
    sys.exit(0)

# Forbidden patterns — sandbox-specific dead ends. Anti-pattern #10.
rules = [
    (
        r"pip\s+install[^|&;]*notebooklm",
        "'pip install notebooklm-py' in sandbox — anti-pattern #10. "
        "The CLI + auth live on Matt's Mac; the sandbox has no display for OAuth "
        "and is wiped every session. Route via mcp__desktop-commander__start_process "
        "(command=\"notebooklm ...\", shell=\"zsh\", timeout_ms=90000) instead."
    ),
    (
        r"pip\s+install[^|&;]*playwright",
        "'pip install playwright' in sandbox — 100+ MB download into ephemeral env "
        "with no display. Playwright is already installed on Matt's Mac as part of "
        "the notebooklm-py browser setup. Use desktop-commander to reach it."
    ),
    (
        r"(^|[\s;&|])playwright\s+install",
        "'playwright install' in sandbox — no display for browser automation, and "
        "the download (~106 MB) is wiped at session end. Already done on Matt's Mac."
    ),
    (
        r"(^|[\s;&|(])notebooklm\s+(ask|use|login|source|auth|notebook|chat)",
        "Bare 'notebooklm ...' in sandbox Bash — CLI doesn't exist here. "
        "Invoke Skill(notebooklm) and route via mcp__desktop-commander__start_process. "
        "See wiki/concepts/notebooklm-workflow.md and anti-pattern #10."
    ),
]

for pattern, reason in rules:
    if re.search(pattern, cmd):
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(out))
        sys.exit(0)

print("")
sys.exit(0)
PYEOF
)

if [ -n "$RESULT" ]; then
  echo "$RESULT"
fi

exit 0
