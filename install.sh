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
#   9. Renders + wires the nightly self-heal scheduler (launchd LaunchAgent)

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
echo "[1/9] Installing Python dependencies..."
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
echo "[2/9] Installing Playwright chromium..."
if command -v playwright &> /dev/null; then
  playwright install chromium 2>&1 | tail -3
  echo "  ✓ Playwright chromium installed"
else
  echo "  ⚠ playwright not on PATH yet — run 'playwright install chromium' after install completes"
fi

# --- 3. Skills ---
echo "[3/9] Installing skills to ~/.claude/skills/..."
SKILLS_DIR="$HOME/.claude/skills"
# DYNAMIC — enumerate canonical skills/ rather than a hardcoded list. Until
# 2026-08-24 this was the THIRD hardcoded copy of "which skills exist", beside
# .claude-plugin/plugin.json and the preflight's sync loop, so removing a skill
# meant editing three places and forgetting one left a dangling reference.
# Add or remove a skill directory and this, and the preflight, both follow.
for skill_dir in "$SCRIPT_DIR/skills/"*/; do
  [ -f "$skill_dir/SKILL.md" ] || continue
  skill=$(basename "$skill_dir")
  mkdir -p "$SKILLS_DIR/$skill"
  cp "$skill_dir/SKILL.md" "$SKILLS_DIR/$skill/SKILL.md"
  echo "  ✓ $skill skill installed"
done
echo "  (limitless-stack = 7-tool protocol; notebooklm = full NotebookLM API;"
echo "   roll-call = session-start preflight;"
echo "   audit-before-claim = verify-then-state, incl. availability claims + tools/recall.sh;"
echo "   karpathy-guidelines = surgical-change discipline borrowed from forrestchang/andrej-karpathy-skills)"

# --- 4. Vault template ---
if [ ! -d "$TARGET/wiki" ]; then
  echo "[4/9] Copying vault template..."
  cp -r "$SCRIPT_DIR/obsidian/vault-template/wiki" "$TARGET/wiki"
  mkdir -p "$TARGET/raw/openscaffold-repos"
  echo "  ✓ wiki/ and raw/ created"
else
  echo "[4/9] wiki/ already exists — skipping vault template"
fi

# --- 5. Tool scripts ---
echo "[5/9] Copying tool scripts..."
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
# Loop tools: the nightly self-heal outer loop (Loop 5), the trust-anchor reality
# inspector (Loop 6), and the self-updating anti-patterns gatherer (rec #5).
cp "$SCRIPT_DIR/tools/nightly-selfheal.sh"        "$TARGET/tools/nightly-selfheal.sh"
cp "$SCRIPT_DIR/tools/trust-anchor-check.py"      "$TARGET/tools/trust-anchor-check.py"
cp "$SCRIPT_DIR/tools/anti-pattern-candidates.py" "$TARGET/tools/anti-pattern-candidates.py"
# Shell-safety layer (added 2026-08-24, claude-anti-patterns #72). The `set -u`
# unbound-variable class hit tools/limitless-preflight.sh TWICE, three months
# apart, and the second time the abort exited with the code that means
# "proceed". These three are the PREVENTION half: a static checker, the
# pre-commit gate that runs it, and the behavioural fence for the preflight's
# completion assertion. Shipped to every project so new vaults inherit the
# lesson rather than rediscovering it.
cp "$SCRIPT_DIR/tools/shell-unbound-check.py"    "$TARGET/tools/shell-unbound-check.py"
cp "$SCRIPT_DIR/tools/git-pre-commit.sh"         "$TARGET/tools/git-pre-commit.sh"
cp "$SCRIPT_DIR/tools/install-git-hooks.sh"      "$TARGET/tools/install-git-hooks.sh"
cp "$SCRIPT_DIR/tools/test-preflight-abort.sh"   "$TARGET/tools/test-preflight-abort.sh"
# Citation resolver + its fence (added 2026-08-24). A bare `client/src/...` path
# exists in more than one working tree, and a session resolving one from memory
# disputed a CORRECT citation and nearly filed a false finding. whichtree.sh owns
# the single working-tree enumeration — limitless-preflight.sh CALLS it for the
# routing block rather than repeating the loop, so a project that gets the
# preflight without this file loses that block entirely.
cp "$SCRIPT_DIR/tools/whichtree.sh"              "$TARGET/tools/whichtree.sh"
cp "$SCRIPT_DIR/tools/test-whichtree.sh"         "$TARGET/tools/test-whichtree.sh"
# Log-order fences (added 2026-08-27). wiki/log.md had been written from BOTH
# ends — 70 entries newest-first at the top, the rest ascending — so
# session-bootstrap's `tail -5` reported FILE order and hid a 2026-08-26
# correction recording that Matt had reversed a shipped decision. recall.sh had
# the sibling defect: its count pass counted entry-TITLE matches, its render
# pass skipped headings, so a title-only hit was counted and never listed. Both
# are fixed and both fences are mutation-proven; ship them together with the
# tools they fence, or a scaffolded project inherits the fix with nothing
# holding it in place.
cp "$SCRIPT_DIR/tools/test-session-bootstrap.sh"  "$TARGET/tools/test-session-bootstrap.sh"
cp "$SCRIPT_DIR/tools/test-recall-render.sh"      "$TARGET/tools/test-recall-render.sh"
# The nightly-selfheal launchd plist TEMPLATE (rendered + wired in step 9).
cp "$SCRIPT_DIR/tools/com.openscaffold.nightly-selfheal.plist.template" \
   "$TARGET/tools/com.openscaffold.nightly-selfheal.plist.template"
chmod +x "$TARGET/tools/session-bootstrap.sh" "$TARGET/tools/limitless-preflight.sh" \
         "$TARGET/tools/notebooklm-wiki-refresh.py" "$TARGET/tools/notebooklm-dedupe.py" \
         "$TARGET/tools/nightly-selfheal.sh" "$TARGET/tools/trust-anchor-check.py" \
         "$TARGET/tools/anti-pattern-candidates.py" "$TARGET/tools/shell-unbound-check.py" \
         "$TARGET/tools/git-pre-commit.sh" "$TARGET/tools/install-git-hooks.sh" \
         "$TARGET/tools/test-preflight-abort.sh" \
         "$TARGET/tools/test-session-bootstrap.sh" "$TARGET/tools/test-recall-render.sh" \
         "$TARGET/tools/whichtree.sh" "$TARGET/tools/test-whichtree.sh"
# .git/hooks is NOT version-controlled, so the gate must be installed per clone.
# Do it here rather than leaving it to whoever remembers — that is the whole
# point of the class this guards.
if [ -d "$TARGET/.git" ]; then
  bash "$TARGET/tools/install-git-hooks.sh" "$TARGET" 2>/dev/null | sed 's/^/  /' || \
    echo "  ⚠ pre-commit gate not installed — run: bash tools/install-git-hooks.sh"
else
  echo "  ℹ $TARGET is not a git repo yet — after 'git init', run: bash tools/install-git-hooks.sh"
fi
echo "  ✓ pinecone-sync, pinecone-search, notebooklm-wiki-refresh, notebooklm-dedupe,"
echo "    session-bootstrap, limitless-preflight (the script Roll Call calls),"
echo "    nightly-selfheal (Loop 5), trust-anchor-check (Loop 6), anti-pattern-candidates (rec #5)"
echo "  Note: edit tools/limitless-preflight.sh + notebooklm-wiki-refresh.py to point at"
echo "  YOUR vault path and YOUR NotebookLM bucket IDs before first run."

# --- 6. CLAUDE.md ---
if [ ! -f "$TARGET/CLAUDE.md" ]; then
  echo "[6/9] Copying CLAUDE.md vault schema..."
  sed -n '/^```markdown$/,/^```$/p' "$SCRIPT_DIR/claude-md/vault-schema.md" | sed '1d;$d' > "$TARGET/CLAUDE.md"
  echo "  ✓ CLAUDE.md created — edit the [YOUR DOMAIN] placeholders"
else
  echo "[6/9] CLAUDE.md already exists — skipping"
fi

# --- 7. Self-heal templates ---
echo "[7/9] Copying self-heal templates..."
mkdir -p "$TARGET/self-heal-templates"
cp "$SCRIPT_DIR/self-heal/templates/self-heal.yml" "$TARGET/self-heal-templates/self-heal.yml"
cp "$SCRIPT_DIR/self-heal/templates/self-heal-agent.js" "$TARGET/self-heal-templates/self-heal-agent.js"
cp "$SCRIPT_DIR/self-heal/templates/SELF-HEAL-SETUP.md" "$TARGET/self-heal-templates/SELF-HEAL-SETUP.md"
echo "  ✓ self-heal templates ready — copy into each app repo as needed"

# --- 8. API key check ---
echo "[8/9] Checking API keys..."
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

# --- 9. Nightly self-heal scheduler ---
echo ""
echo "[9/9] Rendering the nightly self-heal scheduler (launchd)..."
NSH_TEMPLATE="$TARGET/tools/com.openscaffold.nightly-selfheal.plist.template"
NSH_PLIST="$TARGET/tools/com.openscaffold.nightly-selfheal.plist"
if [ -f "$NSH_TEMPLATE" ]; then
  # Render the plist with THIS vault's path. '|' as the sed delimiter since the
  # path contains slashes (but not '|').
  sed "s|__VAULT__|$TARGET|g" "$NSH_TEMPLATE" > "$NSH_PLIST"
  if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$NSH_PLIST" >/dev/null 2>&1; then
    echo "  ⚠ rendered plist failed validation — inspect $NSH_PLIST"
  else
    echo "  ✓ rendered $NSH_PLIST (runs $TARGET/tools/nightly-selfheal.sh at 04:10 nightly)"
  fi
  echo "  To ACTIVATE (deliberately NOT auto-installed — run these yourself):"
  echo "    cp \"$NSH_PLIST\" ~/Library/LaunchAgents/"
  echo "    launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.openscaffold.nightly-selfheal.plist"
  echo "    launchctl kickstart -k gui/\$(id -u)/com.openscaffold.nightly-selfheal   # optional: test-run now"
else
  echo "  ⚠ plist template not found ($NSH_TEMPLATE) — scheduler not rendered"
fi

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
