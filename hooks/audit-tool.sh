#!/bin/bash
# PostToolUse hook — append-only JSONL log of every tool call.
# Pure logging, no enforcement. Feeds future pattern-mining for new anti-patterns.
#
# Input (stdin JSON): tool_name, tool_input, tool_response, tool_use_id, session_id
# Output: exit 0, no stdout (non-blocking)

VAULT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG="$VAULT/.claude/hooks/tool-audit.jsonl"

mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)

LOG="$LOG" INPUT_JSON="$INPUT" python3 - <<'PYEOF' 2>/dev/null || exit 0
import os, sys, json, time

log_path = os.environ.get("LOG")
raw = os.environ.get("INPUT_JSON", "")
if not log_path:
    sys.exit(0)

try:
    data = json.loads(raw) if raw else {}
except Exception:
    sys.exit(0)

tool = data.get("tool_name", "unknown")
tool_input = data.get("tool_input", {})
tool_response = data.get("tool_response", "")
session = data.get("session_id", "unknown")

try:
    input_summary = json.dumps(tool_input)[:500]
except Exception:
    input_summary = "<unserializable>"

if isinstance(tool_response, str):
    resp_len = len(tool_response)
elif isinstance(tool_response, (list, dict)):
    try:
        resp_len = len(json.dumps(tool_response))
    except Exception:
        resp_len = -1
else:
    resp_len = -1

entry = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "session": session,
    "tool": tool,
    "input": input_summary,
    "response_len": resp_len,
}

try:
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
except Exception:
    pass
PYEOF

exit 0
