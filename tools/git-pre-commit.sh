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

# Staged files (Added/Copied/Modified/Renamed — never Deleted).
#   STAGED     — shell only; the bash-syntax + unbound-variable loop below.
#   STAGED_ANY — shell AND python under tools/; the path-portability gate.
# BOTH are computed before ANY early exit. The path gate first shipped BELOW the
# shell-only `[ -z "$STAGED" ] && exit 0`, so a python-only commit returned
# before ever reaching it — and a deliberately-violating .py probe committed
# clean. That is anti-pattern #61: a guard placed downstream of the check that
# rejects its own trigger. Caught 2026-08-24 by an end-to-end probe, not by
# reading the code.
STAGED="$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.sh$' || true)"
STAGED_ANY="$(git diff --cached --name-only --diff-filter=ACMR \
              | grep -E '^tools/.*\.(sh|py)$' || true)"
[ -z "$STAGED" ] && [ -z "$STAGED_ANY" ] && exit 0

if [ -n "$STAGED" ]; then
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
fi   # end: shell-file checks (skipped when no .sh is staged)

# ── Path portability (added 2026-08-24) ─────────────────
# Covers .py AS WELL AS .sh — the loop above is shell-only, so until now every
# Python tool in this repo committed without any gate at all, which is how two
# of them shipped hardcoded Mac paths. Three tools were found on 2026-08-24
# assuming the machine they were authored on and degrading to "I can't check
# that here" everywhere else; each was fixed as an instance. This is the class.
# STAGED_ANY is computed at the TOP of this file — see the note there about why.
if [ -n "$STAGED_ANY" ] && [ -f "$TOOLS/path-portability-check.py" ]; then
  PP_FILES=()
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    pp_copy="$TMP/pp_$(echo "$f" | tr '/' '_')"
    if git show ":$f" > "$pp_copy" 2>/dev/null; then
      # Keep the extension: the checker parses .py docstrings differently.
      mv "$pp_copy" "$pp_copy.${f##*.}"
      PP_FILES+=("$pp_copy.${f##*.}")
    fi
  done <<< "$STAGED_ANY"
  if [ "${#PP_FILES[@]}" -gt 0 ]; then
    echo "pre-commit: checking staged paths for portability"
    # The marker must sit on the EXPANSION line itself — the checker matches per
    # line, and a reason written on the line above is not seen (learned the hard
    # way, same night). :- is wrong here: it would pass an empty string as a
    # filename and the checker would report "cannot read" instead of running.
    if ! pp_out="$(python3.11 "$TOOLS/path-portability-check.py" "${PP_FILES[@]}" 2>&1)"; then   # unbound-ok: guarded non-empty by the [ ${#PP_FILES[@]} -gt 0 ] test above
      # Restore real filenames in the report — the temp copies are unreadable.
      printf '%s\n' "$pp_out" | sed 's|pp_tools_|tools/|; s|\.sh\.sh$|.sh|' | sed 's/^/  /'
      FAIL=1
    else
      echo "  ✓ no unconditional machine-specific paths"
    fi
    echo ""
  fi
fi

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
