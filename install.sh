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
# The nightly-selfheal launchd plist TEMPLATE (rendered + wired in step 9).
cp "$SCRIPT_DIR/tools/com.openscaffold.nightly-selfheal.plist.template" \
   "$TARGET/tools/com.openscaffold.nightly-selfheal.plist.template"
chmod +x "$TARGET/tools/session-bootstrap.sh" "$TARGET/tools/limitless-preflight.sh" \
         "$TARGET/tools/notebooklm-wiki-refresh.py" "$TARGET/tools/notebooklm-dedupe.py" \
         "$TARGET/tools/nightly-selfheal.sh" "$TARGET/tools/trust-anchor-check.py" \
         "$TARGET/tools/anti-pattern-candidates.py"
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

# --- 7b. Claude Code hooks + settings splice ---
#
# WHY THIS STEP EXISTS (added 2026-08-07). Until today the canonical shipped the
# wiki, the tools and the skills — and NO hooks and NO settings.json. So every
# project scaffolded from here had zero PreToolUse gates: nothing stopped a
# session from `pip install notebooklm-py` into the ephemeral sandbox
# (anti-pattern #10) even though the Hub vault had blocked that for months.
# Worse, the preflight's canonical-sync check iterated tools/ and skills/ only,
# so hooks were outside the one mechanism that exists to stop fixes accumulating
# in a single vault. The propagator could not see this class of safeguard —
# anti-pattern #67. Both halves are fixed: the hooks live here, and the preflight
# now sync-checks them.
#
# STATE IS NOT SHIPPED. hooks/.gitignore draws the code/state line
# (tool-audit.jsonl, fabrication-log.jsonl, fabrication-mode are runtime and
# per-vault). This step copies only what is in the canonical hooks/ dir, which
# was populated from `git ls-files` — a structural property, not a hand-kept
# list that can drift (#65 addendum).
echo "[7b/9] Installing Claude Code hooks..."
if [ -d "$SCRIPT_DIR/hooks" ]; then
  mkdir -p "$TARGET/.claude/hooks"
  for h in "$SCRIPT_DIR/hooks/"*; do
    hb=$(basename "$h")
    [ "$hb" = "settings.hooks.json" ] && continue   # template, spliced below — not a hook
    cp "$h" "$TARGET/.claude/hooks/$hb"
  done
  chmod +x "$TARGET/.claude/hooks/"*.sh 2>/dev/null || true
  echo "  ✓ hooks copied to $TARGET/.claude/hooks/"

  # settings.json is MERGED, never overwritten — the target may already have its
  # own permissions, env, or hooks, and clobbering them would be a silent
  # regression of somebody else's configuration. Idempotent: re-running replaces
  # only the hook entries this installer owns (matched by script basename), and
  # leaves every other matcher in place.
  SETTINGS="$TARGET/.claude/settings.json"
  TEMPLATE="$SCRIPT_DIR/hooks/settings.hooks.json"
  if [ -f "$TEMPLATE" ]; then
    if python3 - "$SETTINGS" "$TEMPLATE" <<'PYEOF'
import json, os, sys

settings_path, template_path = sys.argv[1], sys.argv[2]
tmpl = json.load(open(template_path))

if os.path.exists(settings_path):
    try:
        cur = json.load(open(settings_path))
    except Exception as exc:
        sys.stderr.write(f"  existing settings.json is not valid JSON ({exc}) — NOT modified\n")
        sys.exit(1)
else:
    cur = {}

owned = {"session-start.sh", "check-bash.sh", "check-mac-command.sh",
         "audit-tool.sh", "check-fabrication.sh"}

def is_ours(entry):
    for h in entry.get("hooks", []):
        if any(name in h.get("command", "") for name in owned):
            return True
    return False

hooks = cur.setdefault("hooks", {})
added = replaced = kept = 0
for event, entries in tmpl["hooks"].items():
    existing = hooks.get(event, [])
    survivors = [e for e in existing if not is_ours(e)]
    kept += len(survivors)
    replaced += len(existing) - len(survivors)
    hooks[event] = survivors + entries
    added += len(entries)

with open(settings_path, "w") as fh:
    json.dump(cur, fh, indent=2)
    fh.write("\n")
print(f"  ✓ settings.json spliced — {added} hook entr"
      f"{'y' if added == 1 else 'ies'} installed, {replaced} of ours refreshed, "
      f"{kept} pre-existing entr{'y' if kept == 1 else 'ies'} preserved")
PYEOF
    then :; else
      echo "  ⚠ settings.json splice FAILED — hooks are on disk but not wired."
      echo "    Merge $TEMPLATE into $SETTINGS by hand."
    fi
  else
    echo "  ⚠ $TEMPLATE missing — hooks copied but not wired into settings.json"
  fi
else
  echo "  ⚠ $SCRIPT_DIR/hooks not found — no hooks installed (project will have NO PreToolUse gates)"
fi

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
