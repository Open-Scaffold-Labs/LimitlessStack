#!/bin/bash
# Fence for the preflight's DEDUPE_NOTEBOOKS list — ONE ENTRY PER NOTEBOOK.
#
# WHY THIS EXISTS
# The list was built by iterating NOTEBOOK_ROUTES, which is keyed by PATH
# PREFIX, so a notebook receiving many prefixes was emitted once per prefix.
# Measured on the Hub vault manifest 2026-08-27: 25 routes -> 27 entries for 8
# distinct notebooks (openfirehouse 11x, hub 8x). Three real consequences:
#   1. The dedupe sweep backgrounds one fetch per entry, each redirecting to
#      $SWEEP_DIR/$nb_label.json — 11 concurrent writers to ONE path, plus the
#      same .exit sidecar. Measured: 0/40 corrupt while every writer emits
#      identical bytes, 22/40 corrupt once payloads DIFFER. Payloads differ
#      exactly when something is changing the notebook mid-sweep, i.e. the race
#      activates when the check finally has something to report.
#   2. 27 live `notebooklm source list` round trips where 8 suffice (~2.8s each).
#   3. One dirty notebook produced 11 identical warns; a run with 3 distinct
#      findings reported `yellow: 14`.
#
# Usage: bash tools/test-dedupe-notebooks.sh
# Exit: 0 pass · 1 assertion failed · 2 fence could not run

set -eu

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ✓ %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  ✗ %s\n' "$1"; }
die() { printf '  🔴 fence could not run: %s\n' "$1" >&2; exit 2; }

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="$(cd "$SRC_DIR/.." && pwd)"
PF="$SRC_DIR/limitless-preflight.sh"
[ -r "$PF" ] || die "limitless-preflight.sh not found"
bash -n "$PF" || die "limitless-preflight.sh has a syntax error"
ok "limitless-preflight.sh parses"

echo "test-dedupe-notebooks: one entry per notebook, not per route"

# Extract the manifest-reader block from the preflight and run it, so the fence
# tests the SHIPPED code path rather than a reimplementation of it. Anchors are
# the literal lines around the inline python.
EXTRACT="$(sed -n '/^  LIMITLESS_MANIFEST_RAW=\$(python3.11 -c "$/,/^" 2>&1)$/p' "$PF")"
[ -n "$EXTRACT" ] || die "could not locate the manifest-reader block in the preflight"

# Rebuild it as a runnable script with $VAULT substituted, exactly as the
# preflight would expand it.
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$EXTRACT" \
  | sed -e '1s/^  LIMITLESS_MANIFEST_RAW=\$(python3.11 -c "$//' \
        -e '$s/^" 2>&1)$//' \
        -e "s|\$VAULT|$VAULT|g" > "$TMP/reader.py"
[ -s "$TMP/reader.py" ] || die "extracted reader is empty"

RAW="$(python3.11 "$TMP/reader.py" 2>&1)" || die "extracted reader failed to run"
LINE="$(printf '%s\n' "$RAW" | grep '^DEDUPE_NOTEBOOKS=' || true)"
[ -n "$LINE" ] || die "reader emitted no DEDUPE_NOTEBOOKS line"
VAL="${LINE#DEDUPE_NOTEBOOKS=}"

TOTAL="$(printf '%s\n' $VAL | grep -c . || true)"          # unbound-ok: VAL non-empty asserted below
DISTINCT="$(printf '%s\n' $VAL | grep . | sort -u | grep -c . || true)"
[ "${TOTAL:-0}" -gt 0 ] || die "DEDUPE_NOTEBOOKS is empty — the sweep would check NOTHING (coverage floor)"
ok "coverage floor: $TOTAL entries emitted (a zero list would silently check nothing)"

# 1. THE FIX: no repeats.
if [ "$TOTAL" -eq "$DISTINCT" ]; then
  ok "no duplicate entries ($TOTAL total = $DISTINCT distinct)"
else
  bad "DUPLICATES PRESENT: $TOTAL entries for $DISTINCT notebooks — built per route, not per notebook"
  printf '%s\n' $VAL | grep . | sort | uniq -c | sort -rn | sed 's/^/        /' | head -5
fi

# 2. Every entry must be shortid:label — a malformed entry makes nb_id and
#    nb_label collapse to the same string and the sweep fetches nonsense.
BADFORM=0
for e in $VAL; do
  case "$e" in
    *:*) : ;;
    *) BADFORM=$((BADFORM+1)) ;;
  esac
done
if [ "$BADFORM" -eq 0 ]; then
  ok "every entry is shortid:label"
else
  bad "$BADFORM entry(s) missing the ':' separator"
fi

# 3. NEGATIVE CONTROL — the assertion must be able to FAIL. Feed the same
#    checker a list that IS duplicated and require it to notice.
FAKE="aaa:one bbb:two aaa:one"
FT="$(printf '%s\n' $FAKE | grep -c .)"
FD="$(printf '%s\n' $FAKE | grep . | sort -u | grep -c .)"
if [ "$FT" -ne "$FD" ]; then
  ok "negative control: the duplicate test detects a seeded duplicate ($FT vs $FD)"
else
  bad "negative control FAILED — the duplicate test cannot detect duplicates, so assertion 1 is vacuous"
fi

# 4. The summary lines must not hardcode a count. `$((8 - sweep_skipped))` could
#    go negative once the list stopped being 8 long.
#    ⚠ COMMENT LINES ARE EXCLUDED, and that is not a weakened assertion. The
#    first version of this check grepped the whole file and went red on the
#    fix's own explanatory comment, which QUOTES the old expression in backticks
#    to say what was wrong. Verified by reading the single match (line 1597, a
#    comment) against the real code lines, which do use $sweep_count. Testing
#    code by grepping prose is how a fence earns a reputation for lying.
if grep -vE '^[[:space:]]*#' "$PF" | grep -qE 'across 8 notebooks|\$\(\(8 - sweep_skipped\)\)'; then
  bad "a summary line still hardcodes 8 notebooks (non-comment line)"
else
  ok "summary lines count the list instead of hardcoding it (comments excluded)"
fi

echo ""
echo "  passed: $PASS   failed: $FAIL"
# MUTATION: delete the `dedupe_items = list(dict.fromkeys(dedupe_items))` line
# from limitless-preflight.sh and assertion 1 must go red.
[ "$FAIL" -eq 0 ] || exit 1
exit 0
