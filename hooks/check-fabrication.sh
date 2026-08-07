#!/bin/bash
# Stop hook — fabrication scanner.
# Scans the pending assistant message for computer:// URLs and verifies each path.
# Mode: log (default) | enforce. Stored in .claude/hooks/fabrication-mode.
#
# Input (stdin JSON): assistant_message_preview, session_id
# Output on log mode: exit 0, no stdout (just appends to fabrication-log.jsonl)
# Output on enforce: JSON {decision:"block", reason:"..."} if fabrication detected

VAULT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG="$VAULT/.claude/hooks/fabrication-log.jsonl"
MODE_FILE="$VAULT/.claude/hooks/fabrication-mode"

mkdir -p "$(dirname "$LOG")"

MODE="log"
if [ -f "$MODE_FILE" ]; then
  MODE=$(tr -d ' \n\r' <"$MODE_FILE")
fi

INPUT=$(cat)

RESULT=$(INPUT_JSON="$INPUT" LOG_PATH="$LOG" MODE="$MODE" python3 - <<'PYEOF'
import os, json, sys, re, time, urllib.parse

raw = os.environ.get("INPUT_JSON", "")
log_path = os.environ.get("LOG_PATH", "")
mode = os.environ.get("MODE", "log")

try:
    data = json.loads(raw) if raw else {}
except Exception:
    sys.exit(0)

msg = data.get("assistant_message_preview") or data.get("stop_reason", "") or ""
# Fallback: the full input as one big string — search it for computer:// anyway.
if not msg:
    msg = raw

session = data.get("session_id", "unknown")

# Extract computer:// URLs. Two forms:
#   1. Markdown link: [text](computer://path-with-maybe-spaces)  — URL ends at ')'
#   2. Bare URL: computer://path — URL ends at whitespace, ')', '>', ']',
#      backtick, quote, or the Unicode ellipsis (`…`).
# Form 1 is handled first because the vault path literally contains a space
# (/sessions/.../mnt/obsidian ), so bare-URL parsing would truncate there.
# Backticks and quotes are excluded from the bare-URL terminator class to
# stop "talking about a `computer://` link" inside markdown code-quotes from
# false-positiving — see tools/cowork-fabrication-scanner.py for the full
# rationale (this hook keeps regex parity with that scanner).
TRAILING_PUNCT = ',.;:!?'
PATH_HAS_ALNUM = re.compile(r'[A-Za-z0-9]')
urls = []
for m in re.finditer(r'\]\((computer://[^)]+)\)', msg):
    urls.append(m.group(1).rstrip(TRAILING_PUNCT))
# Strip markdown-link URLs from msg before bare-URL scan so we don't double-count
msg_stripped = re.sub(r'\]\(computer://[^)]+\)', ']', msg)
for m in re.finditer(r'computer://[^\s)>\]`"\'…]+', msg_stripped):
    urls.append(m.group(0).rstrip(TRAILING_PUNCT))
# Drop scheme-only and pure-punctuation paths (regex artifacts from prose).
def _has_alnum_path(u):
    if not u.startswith("computer://") or u == "computer://":
        return False
    return bool(PATH_HAS_ALNUM.search(u[len("computer://"):]))
urls = [u for u in urls if _has_alnum_path(u)]
urls = list(dict.fromkeys(urls))  # dedupe, preserve order

if not urls:
    sys.exit(0)

def url_to_path(u: str) -> str:
    p = u[len("computer://"):]
    # URL-decode: the vault path contains literal spaces (and a trailing space),
    # so legitimate computer:// URLs arrive percent-encoded as %20. Without this
    # the existence check would false-positive on every valid vault link and
    # block every legitimate wrap-up once enforce mode is on.
    p = urllib.parse.unquote(p)
    if p.startswith("/"):
        return p
    return "/" + p

missing = []
for u in urls:
    p = url_to_path(u)
    if not os.path.exists(p):
        missing.append({"url": u, "path": p})

# Log EVERY invocation that had URLs to check — both clean and dirty.
# "clean" entries give us the denominator for the flip-to-enforce milestone
# (need ≥20 URL-bearing Stop events with 0 unresolved regex FPs).
# Messages with no URLs at all are still skipped (fast path, nothing to learn).
try:
    with open(log_path, "a") as f:
        f.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session": session,
            "mode": mode,
            "status": "clean" if not missing else "dirty",
            "missing": missing,
            "total_urls": len(urls),
        }) + "\n")
except Exception:
    pass

if mode == "enforce" and missing:
    summary = ", ".join(m["url"] for m in missing[:3])
    more = f" (+{len(missing)-3} more)" if len(missing) > 3 else ""
    reason = (
        f"Fabrication detected: {summary}{more} — these computer:// paths don't "
        f"exist on disk. Don't claim files you didn't actually create. Use the "
        f"Write tool to create the file first, then cite its path. If you believe "
        f"the file should exist, verify with Read or ls before linking."
    )
    print(json.dumps({"decision": "block", "reason": reason}))

sys.exit(0)
PYEOF
)

if [ -n "$RESULT" ]; then
  echo "$RESULT"
fi

exit 0
