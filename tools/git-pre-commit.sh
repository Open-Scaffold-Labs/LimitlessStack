#!/bin/bash
# The pre-commit gate for this repo's shell tooling.
#
# WHY. The completion assertion added 2026-08-24 makes a broken preflight die
# LOUDLY instead of exiting with the code that means "proceed". That is
# DETECTION. Matt's push-back was the right one: detection is the second line,
# not the first. This file is the first line — the `set -u` unbound-variable
# class cannot be COMMITTED, so it never reaches a run to be detected in.
#
# It checks the STAGED content (`git show :file`), not the working tree, so
# `git add -p` of a partial hunk is judged on what is actually being committed.
#
# Escape hatch, stated plainly rather than hidden: `git commit --no-verify`
# skips this. It exists for emergencies. If you use it on a tools/*.sh change,
# say so in the commit message — a silent bypass is how a gate becomes theatre.
#
# Installed by tools/install-git-hooks.sh. The LOGIC lives here (tracked +
# canonical-synced); .git/hooks/pre-commit is a 3-line shim, because .git/hooks
# is not version-controlled and cannot be.
set -u

ROOT="$(git rev-parse --show-toplevel)"
TOOLS="$ROOT/tools"
FAIL=0
TMP="$(mktemp -d -t precommit)"
trap 'rm -rf "$TMP"' EXIT

# Staged shell files (Added/Copied/Modified/Renamed — never Deleted).
STAGED="$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.sh$' || true)"
[ -z "$STAGED" ] && exit 0

echo ""
echo "pre-commit: checking staged shell files"

while IFS= read -r f; do
  [ -z "$f" ] && continue
  staged_copy="$TMP/$(echo "$f" | tr '/' '_')"
  git show ":$f" > "$staged_copy" 2>/dev/null || continue

  if ! bash -n "$staged_copy" 2>"$TMP/syntaxerr"; then
    echo "  ✗ $f — bash syntax error:"
    sed 's/^/      /' "$TMP/syntaxerr"
    FAIL=1
    continue
  fi

  if [ -x "$TOOLS/shell-unbound-check.py" ] || [ -f "$TOOLS/shell-unbound-check.py" ]; then
    if ! out="$(python3.11 "$TOOLS/shell-unbound-check.py" "$staged_copy" 2>&1)"; then
      echo "  ✗ $f — unbound-variable risk in the STAGED content:"
      printf '%s\n' "$out" | grep -E '^      ' | sed 's/^/  /'
      FAIL=1
      continue
    fi
  fi
  echo "  ✓ $f"
done <<< "$STAGED"

# The preflight is the file this whole gate exists because of, so when it is
# being committed, run its behavioural fence too (fast mode, ~2s: abort→exit 2,
# --help→0, network_abort→3, plus the negative control).
if printf '%s\n' "$STAGED" | grep -q 'tools/limitless-preflight.sh'; then
  if [ -f "$TOOLS/test-preflight-abort.sh" ]; then
    echo "  · limitless-preflight.sh staged — running its abort fence"
    if ! fence="$(bash "$TOOLS/test-preflight-abort.sh" 2>&1)"; then
      printf '%s\n' "$fence" | sed 's/^/    /'
      FAIL=1
    else
      printf '%s\n' "$fence" | grep -E 'passed|✗' | sed 's/^/    /'
    fi
    echo "    (fence ran against the WORKING TREE, not the staged blob —"
    echo "     it needs the whole tools/ layout to execute)"
  fi
fi

echo ""
if [ "$FAIL" -ne 0 ]; then
  echo "  COMMIT BLOCKED. Fix the findings above, or — if a flagged line is"
  echo "  genuinely safe — mark that line with an explicit reason:"
  echo ""
  echo "      for x in \"\${ARR[@]}\"; do   # unbound-ok: reached only when N > 0"
  echo ""
  echo "  Under bash 3.2 (this Mac's /bin/bash) even a DECLARED EMPTY array"
  echo "  errors under set -u, and blanket-adding :- changes loop behaviour —"
  echo "  so the marker asks you to state WHY it is safe, not to silence it."
  echo ""
  exit 1
fi
echo "  all staged shell files clean"
echo ""
exit 0
