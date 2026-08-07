#!/bin/bash
# SessionStart hook — Limitless Stack preflight reminder.
# Fires on every session startup. stdout is injected into Claude's context
# before the first token, so Roll Call becomes unconditional.
#
# IMPORTANT: this hook runs in Claude's execution environment (sandbox in Cowork,
# Mac if running Claude Code locally). The full preflight (tools/limitless-preflight.sh)
# needs Mac-native tools (Keychain, notebooklm CLI) which the sandbox can't run.
# This hook does sandbox-side checks only + reminds Claude to run the full preflight
# via Skill(roll-call) + mcp__desktop-commander__start_process.

VAULT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "═══════════════════════════════════════════════════════"
echo "  LIMITLESS STACK — AUTO-PREFLIGHT (SessionStart hook)"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Sandbox-side checks ──
echo "Vault integrity (sandbox-side):"

if [ -r "$VAULT/CLAUDE.md" ]; then
  LINES=$(wc -l <"$VAULT/CLAUDE.md" 2>/dev/null | tr -d ' ')
  echo "  ✓ CLAUDE.md readable ($LINES lines)"
else
  echo "  ✗ CLAUDE.md missing or unreadable — verify vault mount at $VAULT"
fi

if [ -r "$VAULT/wiki/index.md" ]; then
  PAGES=$(find "$VAULT/wiki" -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
  echo "  ✓ wiki/index.md readable · $PAGES pages in wiki/"
else
  echo "  ✗ wiki/index.md missing — verify vault mount"
fi

if command -v git >/dev/null 2>&1 && [ -d "$VAULT/.git" ]; then
  UNCOMMITTED=$(git -C "$VAULT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$UNCOMMITTED" -eq 0 ]; then
    echo "  ✓ git clean"
  else
    echo "  ⚠ $UNCOMMITTED uncommitted files in vault"
  fi
fi

echo ""
echo "MANDATORY: invoke the roll-call skill to run the full Mac-side preflight."
echo "The sandbox cannot verify Pinecone auth, NotebookLM auth, or reminder-notebook"
echo "freshness — those checks live on Matt's Mac. Skill(roll-call) routes the full"
echo "preflight via mcp__desktop-commander__start_process."
echo ""
echo "Preflight script: $VAULT/tools/limitless-preflight.sh"
echo ""
echo "USAGE REMINDERS — routing contract for this session:"
echo "  • Obsidian wiki  → Read/Edit via \$CLAUDE_PROJECT_DIR."
echo "                      For substantive claims: Skill(four-tool-lookup)."
echo "  • Pinecone       → python3.11 tools/pinecone-search.py \"...\" via desktop-commander."
echo "                      API key in Mac Keychain, not in sandbox."
echo "  • NotebookLM     → Skill(notebooklm) for ANY NotebookLM op."
echo "                      CLI via mcp__desktop-commander__start_process("
echo "                        command=\"notebooklm use <id> && notebooklm ask '...'\","
echo "                        shell=\"zsh\", timeout_ms=90000)"
echo "                      NEVER pip install notebooklm-py or notebooklm login in sandbox."
echo "                      Reminder layer: ab4b7ccb  ·  Full wiki mirror: cdaa7a43"
echo "  • CLAUDE.md      → Trust anchor; read at session start."
echo "  • End-of-session → git commit+push · pinecone-sync --changed-only ·"
echo "                      notebooklm-wiki-refresh if wiki changed ·"
echo "                      refresh ab4b7ccb sources if curated files changed"
echo ""
echo "Active hard gates (vault-level .claude/settings.json):"
echo "  • PreToolUse  → blocks pip-install-notebooklm / playwright / bare notebooklm in sandbox Bash"
echo "  • PostToolUse → logs every tool call to .claude/hooks/tool-audit.jsonl"
echo "  • Stop        → scans outgoing messages for fabricated computer:// paths (log-only)"
echo ""
echo "═══════════════════════════════════════════════════════"

exit 0
