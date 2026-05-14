#!/bin/bash
# Limitless Stack — Install Script
# Wires up the entire Limitless Stack from this repo.
#
# Usage:
#   ./install.sh <target-vault-path>
#
# What it does:
#   1. Installs all Python dependencies (pinecone, notebooklm-py, etc.)
#   2. Installs Playwright for NotebookLM browser auth
#   3. Installs skills (limitless-stack + notebooklm) to ~/.claude/skills/
#   4. Copies the vault template (wiki skeleton) if wiki/ doesn't exist
#   5. Copies tool scripts (pinecone-sync, pinecone-search, session-bootstrap, etc.)
#   6. Copies CLAUDE.md vault schema template
#   7. Copies self-heal templates for app repos
#   8. Checks for API keys (the only thing you need to set up manually)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:?Usage: ./install.sh <target-vault-path>}"

echo "=== Limitless Stack Installer ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $TARGET"
echo ""

# --- Create target if needed ---
mkdir -p "$TARGET"

# --- 1. Python dependencies ---
echo "[1/8] Installing Python dependencies..."
if command -v python3.11 &> /dev/null; then
  PYTHON=python3.11
  PIP=pip3.11
elif command -v python3 &> /dev/null; then
  PYTHON=python3
  PIP=pip3
else
  echo "  ✗ Python 3 not found. Install via: brew install python@3.11"
  echo "  Continuing with remaining steps..."
  PYTHON=""
  PIP=""
fi

if [ -n "$PIP" ]; then
  $PIP install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>&1 | tail -5
  echo "  ✓ pinecone, python-docx, pdfplumber, notebooklm-py[browser] installed"
fi

# --- 2. Playwright (for NotebookLM browser auth) ---
echo "[2/8] Installing Playwright chromium..."
if command -v playwright &> /dev/null; then
  playwright install chromium 2>&1 | tail -3
  echo "  ✓ Playwright chromium installed"
else
  echo "  ⚠ playwright not on PATH yet — run 'playwright install chromium' after install completes"
fi

# --- 3. Skills ---
echo "[3/8] Installing skills to ~/.claude/skills/..."
SKILLS_DIR="$HOME/.claude/skills"
for skill in limitless-stack notebooklm four-tool-lookup roll-call verify-before-claim karpathy-guidelines audit-before-claim; do
  mkdir -p "$SKILLS_DIR/$skill"
  cp "$SCRIPT_DIR/skills/$skill/SKILL.md" "$SKILLS_DIR/$skill/SKILL.md"
  echo "  ✓ $skill skill installed"
done
echo "  (limitless-stack = 7-tool protocol; notebooklm = full NotebookLM API;"
echo "   four-tool-lookup = wiki → Pinecone → NotebookLM discipline;"
echo "   roll-call = session-start preflight; verify-before-claim = guard against false unavailability claims;
   karpathy-guidelines = surgical-change discipline borrowed from forrestchang/andrej-karpathy-skills)"

# --- 4. Vault template ---
if [ ! -d "$TARGET/wiki" ]; then
  echo "[4/8] Copying vault template..."
  cp -r "$SCRIPT_DIR/obsidian/vault-template/wiki" "$TARGET/wiki"
  mkdir -p "$TARGET/raw/openscaffold-repos"
  echo "  ✓ wiki/ and raw/ created"
else
  echo "[4/8] wiki/ already exists — skipping vault template"
fi

# --- 5. Tool scripts ---
echo "[5/8] Copying tool scripts..."
mkdir -p "$TARGET/tools"
# Pinecone sync + search
cp "$SCRIPT_DIR/pinecone/pinecone-sync.py" "$TARGET/tools/pinecone-sync.py"
cp "$SCRIPT_DIR/pinecone/pinecone-search.py" "$TARGET/tools/pinecone-search.py"
# NotebookLM operational tools
cp "$SCRIPT_DIR/tools/notebooklm-wiki-refresh.py" "$TARGET/tools/notebooklm-wiki-refresh.py"
cp "$SCRIPT_DIR/tools/notebooklm-dedupe.py" "$TARGET/tools/notebooklm-dedupe.py"
# Session lifecycle scripts
cp "$SCRIPT_DIR/tools/session-bootstrap.sh" "$TARGET/tools/session-bootstrap.sh"
cp "$SCRIPT_DIR/tools/limitless-preflight.sh" "$TARGET/tools/limitless-preflight.sh"
chmod +x "$TARGET/tools/session-bootstrap.sh" "$TARGET/tools/limitless-preflight.sh" \
         "$TARGET/tools/notebooklm-wiki-refresh.py" "$TARGET/tools/notebooklm-dedupe.py"
echo "  ✓ pinecone-sync, pinecone-search, notebooklm-wiki-refresh, notebooklm-dedupe,"
echo "    session-bootstrap, limitless-preflight (the script Roll Call calls)"
echo "  Note: edit tools/limitless-preflight.sh + notebooklm-wiki-refresh.py to point at"
echo "  YOUR vault path and YOUR NotebookLM bucket IDs before first run."

# --- 6. CLAUDE.md ---
if [ ! -f "$TARGET/CLAUDE.md" ]; then
  echo "[6/8] Copying CLAUDE.md vault schema..."
  sed -n '/^```markdown$/,/^```$/p' "$SCRIPT_DIR/claude-md/vault-schema.md" | sed '1d;$d' > "$TARGET/CLAUDE.md"
  echo "  ✓ CLAUDE.md created — edit the [YOUR DOMAIN] placeholders"
else
  echo "[6/8] CLAUDE.md already exists — skipping"
fi

# --- 7. Self-heal templates ---
echo "[7/8] Copying self-heal templates..."
mkdir -p "$TARGET/self-heal-templates"
cp "$SCRIPT_DIR/self-heal/templates/self-heal.yml" "$TARGET/self-heal-templates/self-heal.yml"
cp "$SCRIPT_DIR/self-heal/templates/self-heal-agent.js" "$TARGET/self-heal-templates/self-heal-agent.js"
cp "$SCRIPT_DIR/self-heal/templates/SELF-HEAL-SETUP.md" "$TARGET/self-heal-templates/SELF-HEAL-SETUP.md"
echo "  ✓ self-heal templates ready — copy into each app repo as needed"

# --- 8. API key check ---
echo "[8/8] Checking API keys..."
KEYS_MISSING=false

if security find-generic-password -s pinecone-api-key &> /dev/null 2>&1; then
  echo "  ✓ Pinecone API key in Keychain"
else
  echo "  ✗ Pinecone API key not set — run:"
  echo "    security add-generic-password -a pinecone -s pinecone-api-key -U -w YOUR_KEY"
  KEYS_MISSING=true
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "  ✓ Anthropic API key set in environment"
else
  echo "  ⚠ ANTHROPIC_API_KEY not in environment (needed for self-healing pipeline)"
  echo "    Add to your shell profile: export ANTHROPIC_API_KEY=your_key"
  KEYS_MISSING=true
fi

# --- NotebookLM auth ---
echo ""
echo "  Note: NotebookLM requires browser-based Google auth."
echo "  Run 'notebooklm login' to authenticate (one-time setup)."

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Everything is installed. What Dale (or anyone) does next:"
echo ""
echo "  1. Edit $TARGET/CLAUDE.md — set your domain and customize"
echo "  2. Clone repos into $TARGET/raw/openscaffold-repos/"
echo "  3. Run: $PYTHON $TARGET/tools/pinecone-sync.py"
echo "  4. Run: notebooklm login  (one-time Google auth)"
echo "  5. Run: bash $TARGET/tools/session-bootstrap.sh"
echo ""
if [ "$KEYS_MISSING" = true ]; then
  echo "⚠ API keys still need to be set (see above). Everything else is ready."
else
  echo "✓ All set. The Limitless Stack is ready."
fi
