#!/bin/bash
# Install the pre-commit gate into one or more repos.
#
#   bash tools/install-git-hooks.sh                 # vault + LimitlessStack
#   bash tools/install-git-hooks.sh /path/to/repo   # a specific repo
#   bash tools/install-git-hooks.sh --check         # report, install nothing
#
# HONEST LIMITATION, up front: `.git/hooks/` is NOT version-controlled and
# cannot be. Cloning either repo fresh gets you the tools but NOT the hook —
# this installer has to be run once per clone. That is a git constraint, not a
# design choice. What IS tracked and canonical-synced is tools/git-pre-commit.sh
# (all the logic); the installed hook is a 3-line shim that calls it, so the
# gate's behaviour still evolves through the normal sync contract.
set -u

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
LIMITLESS_STACK_HOME="${LIMITLESS_STACK_HOME:-/Users/matthewlavin/LimitlessStack}"
CHECK_ONLY=false
TARGETS=()

for a in "$@"; do
  case "$a" in
    --check) CHECK_ONLY=true ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) TARGETS+=("$a") ;;
  esac
done
if [ "${#TARGETS[@]}" -eq 0 ]; then                # unbound-ok: ${#…} is a count, always defined
  TARGETS=("$VAULT" "$LIMITLESS_STACK_HOME")
fi

installed=0
skipped=0
for repo in "${TARGETS[@]}"; do                    # unbound-ok: set to a default above when empty
  if [ ! -d "$repo/.git" ]; then
    echo "  ⊘ $repo — not a git repo, skipping"
    skipped=$((skipped + 1))
    continue
  fi
  if [ ! -f "$repo/tools/git-pre-commit.sh" ]; then
    echo "  ⊘ $repo — no tools/git-pre-commit.sh (sync it from the canonical first)"
    skipped=$((skipped + 1))
    continue
  fi
  hook="$repo/.git/hooks/pre-commit"
  if [ -f "$hook" ] && ! grep -q 'git-pre-commit.sh' "$hook"; then
    echo "  ⚠ $repo — a DIFFERENT pre-commit hook is already installed; not overwriting."
    echo "      inspect $hook and merge by hand"
    skipped=$((skipped + 1))
    continue
  fi
  if [ "$CHECK_ONLY" = true ]; then
    if [ -f "$hook" ]; then echo "  ✓ $repo — gate installed"
    else echo "  ✗ $repo — gate NOT installed (run without --check)"; fi
    continue
  fi
  mkdir -p "$repo/.git/hooks"
  cat > "$hook" <<'SHIM'
#!/bin/bash
# Shim — logic lives in tools/git-pre-commit.sh (tracked + canonical-synced).
exec bash "$(git rev-parse --show-toplevel)/tools/git-pre-commit.sh"
SHIM
  chmod +x "$hook"
  echo "  ✓ $repo — pre-commit gate installed"
  installed=$((installed + 1))
done

if [ "$CHECK_ONLY" = false ]; then
  echo ""
  echo "  installed: $installed   skipped: $skipped"
  echo "  bypass (emergencies, and say so in the message): git commit --no-verify"
  echo ""
fi
