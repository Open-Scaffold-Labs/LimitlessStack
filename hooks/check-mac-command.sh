#!/bin/bash
# PreToolUse hook — deny commands that are dead ends ON MATT'S MAC.
# Matcher: mcp__desktop-commander__start_process (configured in .claude/settings.json).
#
# WHY THIS FILE EXISTS AND WHY IT IS NOT IN check-bash.sh
# -------------------------------------------------------
# check-bash.sh is matched on the `Bash` tool, which is the LINUX SANDBOX. The
# commands guarded here fail on the MAC and work fine in the sandbox, so putting
# them in check-bash.sh would be a guard placed where the condition cannot exist
# — anti-pattern #54, and #61 (a guard downstream of the check that rejects its
# own trigger). Two different execution environments need two different gates.
#
# Provenance (2026-08-07): an audit proposed adding a `timeout` -> `gtimeout`
# rule to check-bash.sh. Measured on the Mac before building it, and the
# proposal was wrong three ways: (1) the sandbox Bash tool is not where Mac
# commands run, so the rule could never fire; (2) `gtimeout` is ALSO absent, so
# the corrective pointed at a second missing binary; (3) the premise that the
# failure is silent is false for the bare command — it exits 127 loudly. What is
# genuinely dangerous is `timeout ... 2>/dev/null` or `timeout ... | grep`, where
# the 127 is swallowed and an empty result reads as a clean negative (#42).
#
# Input (stdin JSON): tool_name, tool_input, tool_use_id
# Allow: exit 0, no stdout.   Deny: JSON with permissionDecision="deny".

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
if not tool.endswith("start_process"):
    print("")
    sys.exit(0)

cmd = data.get("tool_input", {}).get("command", "") or ""

rules = [
    (
        r"(^|[\s;&|(])timeout\s+\d",
        "`timeout` does not exist on this Mac — and neither does `gtimeout` "
        "(both verified absent 2026-08-07; bare `timeout` exits 127 with "
        "'command not found'). Do NOT install coreutils to get it: repairing a "
        "blocker by mutating Matt's environment is anti-pattern #58. The failure "
        "is loud on its own, but becomes SILENT the moment you pipe it or send "
        "stderr to /dev/null — then a 127 reads as a clean empty result (#42). "
        "Use the documented long-command pattern instead: "
        "`nohup <cmd> > /tmp/x.log 2>&1 &` then poll the log in a later call."
    ),
]

for pattern, reason in rules:
    if re.search(pattern, cmd):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        sys.exit(0)

print("")
sys.exit(0)
PYEOF
)

if [ -n "$RESULT" ]; then
  echo "$RESULT"
fi

exit 0
