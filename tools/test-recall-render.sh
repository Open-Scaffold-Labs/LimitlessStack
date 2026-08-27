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
echo "  passed: $PASS   failed: $FAIL"
# MUTATION: delete the `if (tolower($0) ~ pat) printf ...` line from the heading
# block in recall.sh and assertions 1 and 2 must go red.
[ "$FAIL" -eq 0 ] || exit 1
exit 0
