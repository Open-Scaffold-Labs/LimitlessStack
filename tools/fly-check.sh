#!/usr/bin/env bash
# fly-check.sh — ask Fly a question WITHOUT letting a logged-out CLI masquerade
# as an access denial.
#
# WHY THIS EXISTS (2026-08-23). "Matt has Fly.io access to paperclip-prod" was
# flipped FIVE times across seven wiki pages. The cause was never carelessness —
# it is that `flyctl status -a <app>` prints
#       Error: ... Could not find App "<app>"
# both when you genuinely lack access AND when you are simply not logged in or
# pointed at the wrong org. `auth whoami` and `orgs list` fail the same way. So a
# session running the check *diligently* gets a false negative, writes "verified
# FALSE" into a trust anchor, and the next session has to re-correct it.
#
# THE RULE THIS ENCODES: a probe used to establish a NEGATIVE must first prove it
# can produce a POSITIVE. Authentication is checked before the verdict, and if
# authentication fails the answer is UNKNOWN — never "no access".
#
# Usage:  tools/fly-check.sh [app-name]        (default: paperclip-prod)
# Exit:   0 = HAVE ACCESS · 1 = NO ACCESS (authenticated, app not visible)
#         2 = UNKNOWN (CLI missing or logged out — NOT a negative result)

set -uo pipefail
APP="${1:-paperclip-prod}"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "UNKNOWN: flyctl is not installed — this is NOT evidence of missing access."
  echo "  fix: brew install flyctl"
  exit 2
fi

WHOAMI="$(flyctl auth whoami 2>&1)"
if [ $? -ne 0 ] || printf '%s' "$WHOAMI" | grep -qi 'no access token\|not logged in\|Error'; then
  echo "UNKNOWN: flyctl is LOGGED OUT — this is NOT evidence of missing access."
  echo "  raw: ${WHOAMI}"
  echo "  fix: flyctl auth login   then re-run: tools/fly-check.sh ${APP}"
  echo "  do NOT record 'no Fly access' from this result. See wiki/concepts/limitless-stack.md."
  exit 2
fi
echo "authenticated as: ${WHOAMI}"

# Positive control: the CLI must be able to see SOMETHING before its inability to
# see one app means anything.
ORGS="$(flyctl orgs list 2>&1)"
if [ $? -ne 0 ] || [ -z "$(printf '%s' "$ORGS" | tr -d '[:space:]')" ]; then
  echo "UNKNOWN: authenticated but 'orgs list' returned nothing — the instrument cannot"
  echo "  demonstrate a positive, so its negative is not trustworthy."
  echo "  raw: ${ORGS}"
  exit 2
fi

if flyctl status -a "$APP" >/dev/null 2>&1; then
  echo "HAVE ACCESS: ${APP} is visible to this authenticated account."
  exit 0
fi

echo "NO ACCESS: authenticated, orgs visible, but ${APP} is not."
echo "  This IS a trustworthy negative — auth and a positive control both passed."
echo "  Before writing it down: this fact has flipped five times. Confirm with Matt,"
echo "  and record it ONLY at its owner page (wiki/concepts/limitless-stack.md)."
exit 1
