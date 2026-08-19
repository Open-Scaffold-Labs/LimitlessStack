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
# Best-effort: never breaks the calling session (always exits 0). Same Keychain
# auth as report-activity.sh. Designed to be called from inside a Cowork session
# (or from any script that wants to record usage).
#
# IT PRINTS ITS OUTCOME BY DEFAULT — one line, success or failure. That is
# deliberate and it is the difference between this and report-activity.sh:
#   * report-activity.sh stays SILENT because preflight/pinecone-sync call it
#     and must not have their output polluted. Do not make that one loud.
#   * track-usage.sh is invoked BY HAND at session close (CLAUDE.md step 9) and
#     nothing calls it programmatically, so silence here bought nothing and cost
#     accuracy: a silent run and a successful run looked identical, and `exit 0`
#     proved dispatch, not landing.
#
# 🔴 DO NOT VERIFY THIS SCRIPT BY RE-RUNNING IT. It has a side effect; every run
# writes another row. Twice now a session has padded its own usage count 3x while
# checking whether the script worked (2026-07-xx: ids 12624/12627/12628;
# 2026-08-18: 14717/14719/14720 — the extras deleted both times). Read the line it
# prints, or query lsh_activity on the Hub project. Re-running a recorder to see
# if it records is a check that changes what it measures.

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
  echo "track-usage: NOT RECORDED — --kind and --name are required." >&2
  exit 0
fi

case "$KIND" in
  skill)      EVENT_TYPE="skill_invoked";  TITLE="invoked $NAME" ;;
  connector)  EVENT_TYPE="connector_used"; TITLE="used $NAME" ;;
  *) echo "track-usage: NOT RECORDED — --kind must be skill or connector (got '$KIND')." >&2; exit 0 ;;
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
  echo "track-usage: NOT RECORDED — report-activity.sh missing at $HELPER" >&2
  exit 0
fi

# LSH_DEBUG is forced ON for the child so we can SEE the API response, then we
# report one clean line ourselves. The child's own debug chatter is captured and
# discarded unless the call failed.
OUT=$(LSH_DEBUG=1 "$HELPER" \
  --source     agent \
  --event-type "$EVENT_TYPE" \
  --actor      "$ACTOR" \
  --title      "$TITLE" \
  --payload    "$PAYLOAD" 2>&1 || true)

if printf '%s' "$OUT" | grep -q '"ok":true'; then
  ID=$(printf '%s' "$OUT" | sed -n 's/.*"id":"\{0,1\}\([0-9]\{1,\}\).*/\1/p' | head -1)
  if [ -n "$ID" ]; then
    echo "track-usage: recorded $KIND \"$NAME\" x$COUNT (id $ID)"
  else
    echo "track-usage: recorded $KIND \"$NAME\" x$COUNT"
  fi
else
  echo "track-usage: FAILED to record $KIND \"$NAME\" — NOT counted." >&2
  printf '%s\n' "$OUT" | tail -3 >&2
fi

# Always 0: telemetry must never break the calling session.
exit 0
