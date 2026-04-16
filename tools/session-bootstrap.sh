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

echo "── RECENT LOG (last 5 operations):"
echo ""
grep "^## \[" "$VAULT/wiki/log.md" | tail -5
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

echo "── OPEN CONTRADICTIONS / WATCHPOINTS:"
grep -r "warning\|contradiction\|unresolved\|⚠️" "$VAULT/wiki/synthesis/architecture.md" 2>/dev/null | head -5
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  Bootstrap complete. Read wiki/index.md next for"
echo "  the full page catalog, then proceed with the task."
echo "═══════════════════════════════════════════════════════"
