#!/usr/bin/env bash
# report-activity.sh — token-gated POST to the Hub's /api/agent-activity/:slug
# endpoint so scheduled scripts and Cowork sessions can write a row into
# lsh_activity. Best-effort: failures must not break the calling script.
#
# Usage:
#   report-activity.sh \
#     --source agent \
#     --event-type preflight \
#     --actor roll-call \
#     --title "preflight READY (23 green · 0 yellow)" \
#     [--repo openscaffold-wiki] \
#     [--url https://...] \
#     [--payload '{"green":23,"yellow":0,"red":0}'] \
#     [--occurred-at 2026-05-18T13:33:46Z]
#
# Required: --source --event-type --title
# Optional: --actor --repo --url --payload --occurred-at
#
# Environment:
#   LSH_HEALTH_URL          Hub base URL  (default: https://limitless-stack-hub.vercel.app)
#   LSH_WORKSPACE_SLUG      Workspace     (default: open-scaffold-labs)
#   LSH_DEBUG               If set, print the curl response instead of swallowing it.
#
# Keychain:
#   Reads the same shared secret as tools/limitless-preflight.sh:
#     security find-generic-password -s lsh-stack-health-token
#   So no separate setup needed — if your preflight already POSTs successfully,
#   this helper will too. If you ever want to use a separate token for
#   activity, set the keychain item `lsh-agent-activity-token` and it'll be
#   preferred over the shared one.
#
# Exit code: always 0. Network/auth failures are logged to stderr only when
# LSH_DEBUG is set. This is intentional — preflight, pinecone-sync, and
# notebooklm-refresh must continue to do their job even if the Hub is down.

set -u
SOURCE=""
EVENT_TYPE=""
ACTOR=""
REPO=""
URL=""
TITLE=""
PAYLOAD="{}"
OCCURRED_AT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --source)       SOURCE="$2";       shift 2 ;;
    --event-type)   EVENT_TYPE="$2";   shift 2 ;;
    --actor)        ACTOR="$2";        shift 2 ;;
    --repo)         REPO="$2";         shift 2 ;;
    --url)          URL="$2";          shift 2 ;;
    --title)        TITLE="$2";        shift 2 ;;
    --payload)      PAYLOAD="$2";      shift 2 ;;
    --occurred-at)  OCCURRED_AT="$2";  shift 2 ;;
    *) [ -n "${LSH_DEBUG:-}" ] && echo "report-activity: unknown arg $1" >&2; shift ;;
  esac
done

if [ -z "$SOURCE" ] || [ -z "$EVENT_TYPE" ] || [ -z "$TITLE" ]; then
  [ -n "${LSH_DEBUG:-}" ] && echo "report-activity: --source, --event-type, --title all required" >&2
  exit 0
fi

# Prefer a dedicated activity token if present, otherwise fall back to the
# shared stack-health token (same reasoning as the server-side fallback in
# server/src/routes/agent-activity.js).
TOKEN=$(security find-generic-password -s lsh-agent-activity-token -w 2>/dev/null || \
        security find-generic-password -s lsh-stack-health-token  -w 2>/dev/null || true)
if [ -z "$TOKEN" ]; then
  [ -n "${LSH_DEBUG:-}" ] && echo "report-activity: no token in keychain (tried lsh-agent-activity-token, lsh-stack-health-token)" >&2
  exit 0
fi

HUB_BASE="${LSH_HEALTH_URL:-https://limitless-stack-hub.vercel.app}"
SLUG="${LSH_WORKSPACE_SLUG:-open-scaffold-labs}"
ENDPOINT="$HUB_BASE/api/agent-activity/$SLUG"

# Build the JSON body via python (avoids shell-escaping headaches with quoted
# titles, unicode, etc.). Python is always available on macOS.
BODY=$(python3 -c '
import json, sys
out = {
  "source":     sys.argv[1],
  "event_type": sys.argv[2],
  "title":      sys.argv[3],
}
if sys.argv[4]: out["actor"]       = sys.argv[4]
if sys.argv[5]: out["repo"]        = sys.argv[5]
if sys.argv[6]: out["url"]         = sys.argv[6]
if sys.argv[7]: out["occurred_at"] = sys.argv[7]
try:
    out["payload"] = json.loads(sys.argv[8]) if sys.argv[8] else {}
except json.JSONDecodeError:
    out["payload"] = {"raw": sys.argv[8]}
print(json.dumps(out))
' "$SOURCE" "$EVENT_TYPE" "$TITLE" "$ACTOR" "$REPO" "$URL" "$OCCURRED_AT" "$PAYLOAD")

if [ -n "${LSH_DEBUG:-}" ]; then
  echo "report-activity: POST $ENDPOINT" >&2
  echo "report-activity: body: $BODY" >&2
  curl -sS --max-time 5 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    "$ENDPOINT" >&2
  echo "" >&2
else
  curl -sS --max-time 5 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    "$ENDPOINT" > /dev/null 2>&1 || true
fi

exit 0
