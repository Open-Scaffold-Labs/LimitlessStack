#!/bin/bash
# Session bootstrap — run this FIRST in every new session.
# Outputs a compact orientation of the current wiki + memory system state.
# Usage: bash tools/session-bootstrap.sh

VAULT="$(cd "$(dirname "$0")/.." && pwd)"

echo "═══════════════════════════════════════════════════════"
echo "  OPENSCAFFOLD MEMORY SYSTEM — SESSION BOOTSTRAP"
echo "═══════════════════════════════════════════════════════"
echo ""

echo "── VAULT: $VAULT"
echo ""

echo "── WIKI OVERVIEW (current thesis):"
echo ""
sed -n '/^## Current thesis/,/^## /p' "$VAULT/wiki/overview.md" | head -20
echo ""

echo "── RECENT LOG (last 5 operations, by ENTRY DATE):"
echo ""
# ⚠ NOT `tail -5` on FILE order. wiki/log.md has been written from BOTH ends:
# 70 entries ran newest-first at the top (lines 5..2452) while the rest ascended.
# Measured 2026-08-27: plain `tail -5` hid the 2026-08-26 entry "THE CAD FILTER
# RAN THE WRONG WAY ROUND — Matt reversed it" — heading index 0 of 668 — from
# every new session's orientation. A prepended entry was invisible here, which
# makes this block a confident-looking lie about what just happened.
# Sort by the entry's own date instead. `sort -s` keeps file order within a day.
# LC_ALL=C is load-bearing, not tidiness: log.md has carried bytes invalid in a
# UTF-8 locale, and `sort` then dies and empties the stream (see tools/recall.sh).
_dated_heads() {
  grep "^## \[" "$VAULT/wiki/log.md" \
    | awk 'match($0,/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/) {
             printf "%s\t%s\n", substr($0, RSTART, RLENGTH), $0 }' \
    | LC_ALL=C sort -s -t"$(printf '\t')" -k1,1
}
_total_heads="$(grep -c "^## \[" "$VAULT/wiki/log.md" 2>/dev/null || true)"
_total_heads="${_total_heads:-0}"
_dated_heads | tail -5 | cut -f2-

# COVERAGE FLOOR: the pipeline above can drop rows (locale, malformed heading).
# Five headings in must mean five out — otherwise say INCOMPLETE rather than
# printing a short list that reads like a quiet week.
_shown="$(_dated_heads | tail -5 | grep -c '^' 2>/dev/null || true)"
_shown="${_shown:-0}"
_want=5
if [ "$_total_heads" -lt 5 ]; then _want="$_total_heads"; fi
if [ "$_shown" -ne "$_want" ]; then
  echo ""
  echo "  🔴 INCOMPLETE — listed $_shown of $_want from $_total_heads headings."
  echo "     The date-sort pipeline dropped rows. Do NOT read this as history."
fi

# DRIFT DETECTOR: with log.md in one order, file-order newest == date newest.
# If they diverge, a session PREPENDED again and the append-only convention
# broke. This is the check whose absence let the defect above run for months.
_file_newest="$(grep "^## \[" "$VAULT/wiki/log.md" | tail -1)"
_date_newest="$(_dated_heads | tail -1 | cut -f2-)"
if [ -n "$_file_newest" ] && [ "$_file_newest" != "$_date_newest" ]; then
  echo ""
  echo "  ⚠ log.md IS OUT OF DATE ORDER — an entry was PREPENDED."
  echo "     file-order newest: ${_file_newest:0:72}"
  echo "     date-order newest: ${_date_newest:0:72}"
  echo "     Convention is APPEND-ONLY (CLAUDE.md). Reflow before citing order."
fi
echo ""

echo "── WIKI PAGE COUNT:"
find "$VAULT/wiki" -name "*.md" | wc -l | xargs echo "  pages:"
echo ""

echo "── PINECONE INDEX STATUS:"
PINECONE_API_KEY=$(security find-generic-password -s pinecone-api-key -w 2>/dev/null) python3.11 -c "
from pinecone import Pinecone; import os
pc = Pinecone(api_key=os.environ.get('PINECONE_API_KEY',''))
s = pc.Index('openscaffold').describe_index_stats()
print(f\"  vectors: {s.get('total_vector_count')}  namespaces: {list(s.get('namespaces',{}).keys())}\")
" 2>/dev/null || echo "  (Pinecone unreachable — check API key)"
echo ""

echo "── REPOS IN RAW:"
ls "$VAULT/raw/openscaffold-repos/" 2>/dev/null | while read d; do echo "  • $d"; done
echo ""

echo "── TOOLS AVAILABLE:"
ls "$VAULT/tools/"*.py "$VAULT/tools/"*.sh 2>/dev/null | while read f; do echo "  • $(basename "$f")"; done
echo ""

echo "── NOTEBOOKLM ACCESS (READ THIS BEFORE RUNNING notebooklm):"
echo "  CLI + auth live on Matt's Mac, NOT in this sandbox."
echo "  Route every call via desktop-commander:"
echo "    mcp__desktop-commander__start_process("
echo "      command=\"notebooklm use <id> && notebooklm ask '...'\","
echo "      shell=\"zsh\", timeout_ms=90000)"
echo "  DO NOT pip-install notebooklm-py or playwright in the sandbox — no display,"
echo "  no auth, wiped every session. See wiki/concepts/notebooklm-workflow.md"
echo "  and anti-pattern #10 in wiki/synthesis/claude-anti-patterns.md."
echo ""

echo "── OPEN CONTRADICTIONS / WATCHPOINTS:"
grep -r "warning\|contradiction\|unresolved\|⚠️" "$VAULT/wiki/synthesis/architecture.md" 2>/dev/null | head -5
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  Bootstrap complete. Read wiki/index.md next for"
echo "  the full page catalog, then proceed with the task."
echo "═══════════════════════════════════════════════════════"
