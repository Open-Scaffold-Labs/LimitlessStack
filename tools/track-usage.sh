#!/usr/bin/env bash
# track-usage.sh — record a single skill invocation or connector tool call.
#
# Thin wrapper around report-activity.sh that fires:
#   source     = "agent"
#   event_type = "skill_invoked"  | "connector_used"
#   actor      = "claude/<user>"  (auto-derived; can be overridden)
#   payload    = { name, count? }
#
# Usage:
#   track-usage.sh --kind skill     --name roll-call
#   track-usage.sh --kind connector --name slack [--count 3]
#   track-usage.sh --kind skill     --name notebooklm --plugin anthropic-skills
#
# Required: --kind {skill|connector} --name <name>
# Optional: --count N   (defaults to 1)
#           --plugin <plugin-name>  (e.g. "engineering" for engineering:debug)
#           --actor <actor>         (defaults to "claude/$(whoami)")
#
# Best-effort: never breaks the calling session. Same Keychain auth as
# report-activity.sh. Designed to be called from inside a Cowork session
# (or from any script that wants to record usage).

set -u
KIND=""
NAME=""
COUNT="1"
PLUGIN=""
ACTOR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kind)    KIND="$2";    shift 2 ;;
    --name)    NAME="$2";    shift 2 ;;
    --count)   COUNT="$2";   shift 2 ;;
    --plugin)  PLUGIN="$2";  shift 2 ;;
    --actor)   ACTOR="$2";   shift 2 ;;
    *) [ -n "${LSH_DEBUG:-}" ] && echo "track-usage: unknown arg $1" >&2; shift ;;
  esac
done

if [ -z "$KIND" ] || [ -z "$NAME" ]; then
  [ -n "${LSH_DEBUG:-}" ] && echo "track-usage: --kind and --name required" >&2
  exit 0
fi

case "$KIND" in
  skill)      EVENT_TYPE="skill_invoked";  TITLE="invoked $NAME" ;;
  connector)  EVENT_TYPE="connector_used"; TITLE="used $NAME" ;;
  *) [ -n "${LSH_DEBUG:-}" ] && echo "track-usage: --kind must be skill or connector (got $KIND)" >&2; exit 0 ;;
esac

# Default actor follows the same "claude/<github-login>" convention used by
# the activity feed (see /activity Agents filter). $(whoami) is the macOS
# user, which on Matt's Mac is "matthewlavin" — close enough as a stand-in
# for the github login until we wire a real session identity.
if [ -z "$ACTOR" ]; then
  WHO=$(whoami 2>/dev/null || echo unknown)
  ACTOR="claude/$WHO"
fi

# Build payload via python so quoting is sane.
PAYLOAD=$(python3 -c '
import json, sys
out = {"name": sys.argv[1], "count": int(sys.argv[2])}
if sys.argv[3]: out["plugin"] = sys.argv[3]
print(json.dumps(out))
' "$NAME" "$COUNT" "$PLUGIN")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$SCRIPT_DIR/report-activity.sh"
if [ ! -x "$HELPER" ]; then
  [ -n "${LSH_DEBUG:-}" ] && echo "track-usage: report-activity.sh missing at $HELPER" >&2
  exit 0
fi

"$HELPER" \
  --source     agent \
  --event-type "$EVENT_TYPE" \
  --actor      "$ACTOR" \
  --title      "$TITLE" \
  --payload    "$PAYLOAD" || true

exit 0
