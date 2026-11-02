#!/bin/bash
# Fence for recall.sh's log.md render pass.
#
# WHY THIS EXISTS
# recall.sh counts hits and renders hits in two separate awk passes. The count
# pass does NOT skip entry headings; the render pass did. So any entry whose only
# match was in its own `## [date] op | label` TITLE was counted and never listed,
# and the tool RENDER FLOOR fired — correctly, loudly, on every such query.
# Measured on the live log 2026-08-27: "cad filter" counted 1 hit / listed 0;
# "type floor" counted 2 entries / listed 1. Searching by entry title is the most
# likely way a session looks for a ruling, so this hit the common path.
#
# Usage: bash tools/test-recall-render.sh
# Exit: 0 pass · 1 assertion failed · 2 fence could not run

set -eu

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ✓ %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  ✗ %s\n' "$1"; }
die() { printf '  🔴 fence could not run: %s\n' "$1" >&2; exit 2; }

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -r "$SRC_DIR/recall.sh" ] || die "recall.sh not found"

# A broken shell string in recall.sh aborts it BEFORE the render, so a grep for
# "RENDER FAILURE" comes back clean. That false green happened for real while
# fixing this. Syntax first, always.
bash -n "$SRC_DIR/recall.sh" || die "recall.sh has a syntax error"
ok "recall.sh parses (guards against the false-green abort)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/vault/tools" "$TMP/vault/wiki" "$TMP/vault/wiki/my-tasks"
cp "$SRC_DIR/recall.sh" "$TMP/vault/tools/"
: > "$TMP/vault/CLAUDE.md"
: > "$TMP/vault/wiki/team-tasks.md"
: > "$TMP/vault/wiki/my-tasks/x.md"
mkdir -p "$TMP/vault/wiki/synthesis"; : > "$TMP/vault/wiki/synthesis/claude-anti-patterns.md"

cat > "$TMP/vault/wiki/log.md" <<'LOG'
# Log

## [2026-05-01] build | zzuniquetitleonly appears only here in the heading
- an unrelated body line
## [2026-05-02] build | an ordinary entry
- the body mentions zzbodyonly right here
## [2026-05-03] build | zzbothplaces in the title
- and zzbothplaces again in the body
LOG

run() { ( cd "$TMP/vault" && bash tools/recall.sh "$1" 2>&1 || true ); }

echo "test-recall-render: title-only matches must be listed"

# 1. TITLE-ONLY match: counted 1 entry, must LIST 1 group, no floor breach.
OUT="$(run zzuniquetitleonly)"
G="$(printf '%s\n' "$OUT" | grep -c '^  ## ' || true)"
if [ "${G:-0}" -eq 1 ] && ! printf '%s' "$OUT" | grep -q 'RENDER FAILURE'; then
  ok "title-only match is listed (1 group, floor quiet)"
else
  bad "title-only match not listed: groups=${G:-0}, floor=$(printf '%s' "$OUT" | grep -c 'RENDER FAILURE' || true)"
fi

# 2. It must be LABELLED as a title match, so the reader is not told a body line
#    exists that does not.
if printf '%s' "$OUT" | grep -q 'match is in the entry TITLE'; then
  ok "title match is labelled as such"
else
  bad "title match rendered without the TITLE label"
fi

# 3. NEGATIVE CONTROL — a body-only match must still render normally, and must
#    NOT be mislabelled as a title match.
OUT2="$(run zzbodyonly)"
if printf '%s' "$OUT2" | grep -q 'zzbodyonly' && ! printf '%s' "$OUT2" | grep -q 'match is in the entry TITLE'; then
  ok "body-only match renders its real line, unlabelled"
else
  bad "body-only match regressed"
fi

# 4. Both places: still exactly one group, not a duplicate.
OUT3="$(run zzbothplaces)"
G3="$(printf '%s\n' "$OUT3" | grep -c '^  ## ' || true)"
if [ "${G3:-0}" -eq 1 ]; then
  ok "title+body match yields one group, not two"
else
  bad "title+body match produced ${G3:-0} groups"
fi

# 5. A miss must stay a miss (no phantom rendering).
OUT4="$(run zznotpresentanywhere)"
if printf '%s' "$OUT4" | grep -q '^  ## '; then
  bad "a query with no hits rendered a group"
else
  ok "no-hit query renders nothing"
fi

echo ""

# ── HISTORY FLOOR (added 2026-09-12) ─────────────────────────────────────────
# A vault with NO wiki/log.md must REFUSE (exit 2), not answer from whichever
# config files happen to be readable. The canonical LimitlessStack checkout is
# exactly that shape — it ships recall.sh but has no wiki/ — and it used to
# answer any query from 2 files / 255 lines with exit 1, which reads as
# "searched, nothing found" rather than "wrong tree". Hermetic: the hub-CLAUDE
# override is pinned so the search cannot wander off and find a real vault.
NOLOG="$(mktemp -d)"
mkdir -p "$NOLOG/vault/tools"
cp "$SRC_DIR/recall.sh" "$NOLOG/vault/tools/"
printf 'placeholder\n' > "$NOLOG/vault/CLAUDE.md"
# `set -e` is active: a bare non-zero subshell aborts the fence BEFORE `$?` can
# be read, which is how this block first "passed" by dying silently at exit 2.
# Same reason the run() helper above carries `|| true`.
RC_NOLOG=0
( cd "$NOLOG/vault" && RECALL_HUB_CLAUDE="$NOLOG/vault/CLAUDE.md" \
    bash tools/recall.sh zzanything >/dev/null 2>&1 ) || RC_NOLOG=$?
if [ "$RC_NOLOG" -eq 2 ]; then
  ok "history floor: a vault with no wiki/log.md exits 2 (the search did not run)"
else
  bad "history floor: expected exit 2 from a historyless vault, got $RC_NOLOG — a zero from it would read as 'never decided'"
fi

# Negative control for the same gate: the fixture vault DOES have a log, so the
# floor must stay out of the way and let a real zero-hit answer be exit 1.
RC_HASLOG=0
( cd "$TMP/vault" && bash tools/recall.sh zznosuchsubjectanywhere >/dev/null 2>&1 ) || RC_HASLOG=$?
if [ "$RC_HASLOG" -eq 1 ]; then
  ok "history floor does not over-fire: a vault WITH a log still answers (exit 1 = searched, no hits)"
else
  bad "history floor over-fired: a vault with wiki/log.md returned $RC_HASLOG, expected 1"
fi
rm -rf "$NOLOG"

echo "  passed: $PASS   failed: $FAIL"
# MUTATION: delete the `if (tolower($0) ~ pat) printf ...` line from the heading
# block in recall.sh and assertions 1 and 2 must go red.
[ "$FAIL" -eq 0 ] || exit 1
exit 0
