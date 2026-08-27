#!/bin/bash
# Fence for session-bootstrap.sh's RECENT LOG block.
#
# WHY THIS EXISTS
# wiki/log.md has been written from BOTH ends. `grep "^## \[" | tail -5` reports
# FILE order, so on 2026-08-27 the newest entry in the file's top block — a
# 2026-08-26 `correction` recording that Matt had REVERSED a shipped decision —
# sat at heading index 0 of 668 and was invisible to every new session's
# orientation. The block looked authoritative and was wrong.
#
# The fence asserts the three properties the fix must have, and it is written so
# that REVERTING the fix turns it red (mutation-proven, see MUTATION below).
#
# Usage: bash tools/test-session-bootstrap.sh
# Exit: 0 all assertions pass · 1 an assertion failed · 2 the fence could not run

set -eu

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ✓ %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  ✗ %s\n' "$1"; }
die()  { printf '  🔴 fence could not run: %s\n' "$1" >&2; exit 2; }

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -r "$SRC_DIR/session-bootstrap.sh" ] || die "session-bootstrap.sh not found"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── build a synthetic vault whose log.md reproduces the real defect ──────────
# Shape: three PREPENDED newest-first entries at the top (the newest of all is
# at heading index 0), then an ascending block. Exactly the real file's shape.
mkdir -p "$TMP/vault/tools" "$TMP/vault/wiki"
cp "$SRC_DIR/session-bootstrap.sh" "$TMP/vault/tools/"

cat > "$TMP/vault/wiki/log.md" <<'LOG'
# Log

Append-only chronological record.

## [2026-08-26] correction | PREPENDED-NEWEST-CANARY
- body line mentioning canary
## [2026-08-20] build | prepended second
- body
## [2026-08-10] build | prepended third
- body
## [2026-04-01] ingest | ascending first
- body
## [2026-04-02] build | ascending second
- body
## [2026-04-03] build | ascending third
- body
## [2026-04-04] build | ascending fourth
- body
## [2026-04-05] build | APPEND-ORDER-TAIL
- body
LOG

printf '## Current thesis\nsynthetic\n## next\n' > "$TMP/vault/wiki/overview.md"

run_bootstrap() {
  # Other sections (pinecone, notebooklm) are expected to fail in the sandbox;
  # we assert only on the RECENT LOG block. `|| true` keeps the fence alive.
  ( cd "$TMP/vault" && bash tools/session-bootstrap.sh 2>/dev/null || true ) \
    | sed -n '/── RECENT LOG/,/── WIKI PAGE COUNT/p'
}

echo "test-session-bootstrap: RECENT LOG ordering"

OUT="$(run_bootstrap)"
[ -n "$OUT" ] || die "RECENT LOG section produced no output at all"

# 1. The prepended-newest entry MUST appear. This is the defect that shipped.
if printf '%s' "$OUT" | grep -q 'PREPENDED-NEWEST-CANARY'; then
  ok "prepended newest entry is visible (file-order tail -5 would hide it)"
else
  bad "prepended newest entry MISSING — the block is reporting file order"
fi

# 2. It must be listed LAST (the list is 'last 5', so newest sorts to the end).
LAST_LINE="$(printf '%s' "$OUT" | grep '^## \[' | tail -1)"
if printf '%s' "$LAST_LINE" | grep -q 'PREPENDED-NEWEST-CANARY'; then
  ok "newest-by-date is listed last"
else
  bad "newest-by-date not last; got: ${LAST_LINE:0:60}"
fi

# 3. The drift detector must FIRE on an out-of-order log.
if printf '%s' "$OUT" | grep -q 'OUT OF DATE ORDER'; then
  ok "drift detector fires on a prepended log"
else
  bad "drift detector silent on a log that IS out of order"
fi

# 4. NEGATIVE CONTROL — a correctly ordered log must NOT trip the detector,
#    or the warning is noise and will be ignored.
python3 - "$TMP/vault/wiki/log.md" <<'PY'
import re, sys
p = sys.argv[1]
txt = open(p, encoding="utf-8").read()
head, sep, _ = txt.partition("## [")
body = sep + _
parts = re.split(r'(?m)^(?=## \[)', body)
parts = [x for x in parts if x.strip()]
parts.sort(key=lambda s: re.search(r'\[(\d{4}-\d{2}-\d{2})\]', s).group(1))
open(p, "w", encoding="utf-8").write(head + "".join(parts))
PY
OUT2="$(run_bootstrap)"
if printf '%s' "$OUT2" | grep -q 'OUT OF DATE ORDER'; then
  bad "drift detector fires on an in-order log (false positive — would be ignored)"
else
  ok "drift detector silent on an in-order log"
fi

# 5. COVERAGE FLOOR must not claim INCOMPLETE on a healthy run.
if printf '%s' "$OUT2" | grep -q 'INCOMPLETE'; then
  bad "coverage floor reports INCOMPLETE on a healthy 8-entry log"
else
  ok "coverage floor quiet on a healthy log"
fi

# 6. FLOOR POSITIVE CONTROL — with fewer than 5 entries it must still not fire.
printf '# Log\n\n## [2026-04-01] build | only one\n- body\n' > "$TMP/vault/wiki/log.md"
OUT3="$(run_bootstrap)"
if printf '%s' "$OUT3" | grep -q 'INCOMPLETE'; then
  bad "coverage floor false-fires when the log has fewer than 5 entries"
else
  ok "coverage floor handles a short log"
fi

echo ""
echo "  passed: $PASS   failed: $FAIL"
# MUTATION: restore `grep "^## \[" ... | tail -5` in session-bootstrap.sh and
# assertions 1, 2 and 3 must go red. If they don't, this fence is decorative.
[ "$FAIL" -eq 0 ] || exit 1
exit 0
