#!/bin/bash
# test-whichtree.sh — the fence for tools/whichtree.sh.
#
# WHY A SYNTHETIC FIXTURE AND NOT MATT'S $HOME. A fence asserting "tokens.css is
# in exactly two trees" is a fence about one Mac on one day — delete the-match
# and it goes red for a reason that has nothing to do with the code. Every
# assertion here runs against `git init` repos built in a temp dir, so the
# ground truth is CONSTRUCTED, known, and identical on any machine.
#
# WHY THE MUTATION IS THE POINT. Three mutation tests were vacuous on 2026-08-24
# — one run from /tmp where the vault self-located empty, one pointed at a path
# that always existed, one whose `sed` errored so its empty output read as a
# pass. So this file, before mutating anything:
#   · asserts the anchor string EXISTS (a sed that matches nothing is a pass
#     that measured nothing),
#   · asserts the rewrite actually CHANGED the file,
#   · asserts the BASELINE contains what the mutant should lose (without this,
#     "the mutant lost it" is satisfied by a tool that never found it at all),
#   · runs the mutant from tools/, where the real one lives.
#
# USAGE   bash tools/test-whichtree.sh
# EXIT    0 all assertions passed · 1 at least one failed

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
WT="$HERE/whichtree.sh"
FIX=""
PASS=0
FAIL=0

cleanup() {
  if [ -n "$FIX" ] && [ -d "$FIX" ]; then rm -rf "$FIX"; fi
  if [ -e "$HERE/whichtree.mutant.sh" ]; then rm -f "$HERE/whichtree.mutant.sh"; fi
}
trap cleanup EXIT

ok()   { PASS=$((PASS+1)); printf '  ✓ %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  ✗ %s\n' "$1"; }

# assert_exit <want> <label> <command...>
assert_exit() {
  local _want="$1" _label="$2"; shift 2
  local _got=0
  "$@" >/dev/null 2>&1 || _got=$?
  if [ "$_got" -eq "$_want" ]; then ok "$_label (exit $_got)"
  else bad "$_label — wanted exit $_want, got $_got"; fi
}

# assert_contains <needle> <label> <command...>
assert_contains() {
  local _needle="$1" _label="$2"; shift 2
  local _out
  _out=$("$@" 2>&1 || true)
  if printf '%s' "$_out" | grep -q -- "$_needle"; then ok "$_label"
  else bad "$_label — output did not contain '$_needle'"; fi
}

echo ""
echo "━━ fence: tools/whichtree.sh"
echo ""

if [ ! -f "$WT" ]; then
  echo "  ✗ tools/whichtree.sh not found at $WT"
  exit 1
fi

# ── build the fixture ─────────────────────────────────────────────────────────
# Clear any mutant a previously KILLED run left behind. The trap below handles
# a normal exit, but a SIGKILL skips it — and a stray whichtree.mutant.sh in
# tools/ would be picked up by the preflight's tools/*.sh scan and could be
# committed by accident.
rm -f "$HERE/whichtree.mutant.sh"

FIX=$(mktemp -d "${TMPDIR:-/tmp}/wt-fixture.XXXXXX")
mkdir -p "$FIX/treeroot" "$FIX/emptyroot"

# Counted as they are built, so adding a fixture below cannot silently invalidate
# the positive control. A literal "4" here went stale the first time a fixture was
# added — the assertion still ran, but it was asserting the wrong number.
NTREES=0

mkrepo() {
  local _name="$1" _file="$2" _dir="$FIX/treeroot/$1"
  local _url="${3:-https://example.invalid/org/$_name.git}"
  NTREES=$((NTREES+1))
  mkdir -p "$_dir"
  git -C "$_dir" init -q 2>/dev/null
  git -C "$_dir" remote add origin "$_url"
  mkdir -p "$_dir/$(dirname "$_file")"
  echo "fixture" > "$_dir/$_file"
  git -C "$_dir" add -A 2>/dev/null
  git -C "$_dir" -c user.email=f@f -c user.name=f commit -qm "fixture" 2>/dev/null
}

mkrepo repoA client/src/design/tokens.css
mkrepo repoB client/src/design/tokens.css
mkrepo solo  unique/only-here.txt

# IDENTITY FIXTURES — the bug found by auditing this tool on 2026-08-24.
# Taking the remote's last path segment was wrong in BOTH directions at once:
#   · credA carries a user@ credential prefix but is the SAME repo as repoA
#     and must MERGE with it.
#   · dupOne and dupTwo share the repo NAME "shared" under DIFFERENT orgs and
#     are DIFFERENT upstreams — they must NOT merge. On Matt's Mac this was live:
#     Open-Scaffold-Labs/paperclip and paperclipai/paperclip were being grouped,
#     so the routing block ranked a vendor checkout against ours as "older".
mkrepo credA  client/src/design/tokens.css "https://user@example.invalid/org/repoA.git"
mkrepo dupOne shared/thing.txt             "https://example.invalid/orgOne/shared.git"
mkrepo dupTwo shared/thing.txt             "git@example.invalid:orgTwo/shared.git"

# A git WORKTREE: its .git is a FILE, not a directory. This is the whole reason
# the enumeration tests -e and not -d, and it is what the mutation below breaks.
git -C "$FIX/treeroot/repoA" -c user.email=f@f -c user.name=f \
    worktree add -q -b fixture-wt "$FIX/treeroot/repoA-wt" 2>/dev/null

if [ -f "$FIX/treeroot/repoA-wt/.git" ]; then
  NTREES=$((NTREES+1))
  ok "fixture: repoA-wt/.git is a FILE (a real git worktree)"
else
  bad "fixture: repoA-wt/.git is not a file — the mutation test would be vacuous"
fi

export WT_HOME="$FIX/treeroot"

# ── positive control: the scan must actually run ──────────────────────────────
assert_contains "scanned $NTREES working tree(s)" \
  "positive control — enumerates all $NTREES fixture trees" \
  bash "$WT" unique/only-here.txt

# ── the five exit states ──────────────────────────────────────────────────────
assert_exit 0 "unique path resolves to exactly one tree" \
  bash "$WT" unique/only-here.txt
assert_contains "solo/unique/only-here.txt" \
  "unique path names the right tree" \
  bash "$WT" unique/only-here.txt

assert_exit 3 "a path in no tree is NOT FOUND" \
  bash "$WT" nope/nothing-here.txt

assert_exit 4 "a path in several trees is AMBIGUOUS" \
  bash "$WT" client/src/design/tokens.css
assert_contains "repoB" "ambiguous listing includes repoB" \
  bash "$WT" client/src/design/tokens.css
assert_contains "repoA" "ambiguous listing includes repoA" \
  bash "$WT" client/src/design/tokens.css

assert_exit 0 "a correctly-formatted <repo>/<path> citation resolves" \
  bash "$WT" repoB/client/src/design/tokens.css
assert_contains "citation is sound" \
  "a sound citation is reported as sound" \
  bash "$WT" repoB/client/src/design/tokens.css

assert_exit 5 "citing a tree that does NOT hold the path is MISATTRIBUTED" \
  bash "$WT" solo/client/src/design/tokens.css
assert_contains "MISATTRIBUTED" \
  "the misattribution is named, not just exit-coded" \
  bash "$WT" solo/client/src/design/tokens.css

assert_exit 0 "a :LINE suffix is stripped, not treated as part of the name" \
  bash "$WT" unique/only-here.txt:412

WT_HOME="$FIX/emptyroot" assert_exit 2 \
  "an empty \$WT_HOME reports SCAN DID NOT RUN, not 'not found'" \
  env WT_HOME="$FIX/emptyroot" bash "$WT" unique/only-here.txt

assert_exit 0 "--list exits 0" bash "$WT" --list
assert_exit 1 "an unknown option is a usage error" bash "$WT" --nonsense

# ── repo IDENTITY: the remote, not its last segment ──────────────────────────
echo ""
echo "  ── identity: a credential prefix must MERGE, a different org must NOT"

assert_contains "org/repoA" \
  "identity is org/repo, not just the repo name" \
  bash "$WT" --list
assert_contains "credA" \
  "a user@ credential prefix MERGES into the same repo's group" \
  bash "$WT" --list

# dupOne and dupTwo are different upstreams that share a name. If identity were
# the last segment they would be grouped, and --list would print a bogus
# "shared — MORE THAN ONE WORKING TREE" ranking one against the other.
if bash "$WT" --list 2>&1 | grep -q "shared — MORE THAN ONE"; then
  bad "two DIFFERENT orgs sharing a repo name were merged into one group"
else
  ok "two different orgs sharing a repo name are NOT merged"
fi

assert_exit 4 "a name shared across orgs still resolves as several trees" \
  bash "$WT" shared/thing.txt
assert_contains "orgOne/shared" "the ambiguity names orgOne" \
  bash "$WT" shared/thing.txt
assert_contains "orgTwo/shared" "the ambiguity names orgTwo (scp-style remote)" \
  bash "$WT" shared/thing.txt

# ── THE MUTATION ──────────────────────────────────────────────────────────────
# Break the worktree test back to -d and require that repoA-wt disappears.
echo ""
echo '  ── mutation: [ -e "$_d/.git" ]  →  [ -d "$_d/.git" ]'

ANCHOR='[ -e "$_d/.git" ] || continue'
if grep -qF -- "$ANCHOR" "$WT"; then
  ok "anchor present before mutating (a sed matching nothing is a vacuous pass)"

  # Baseline MUST contain the worktree, or "the mutant lost it" proves nothing.
  BASE_OUT=$(bash "$WT" --list 2>&1 || true)
  if printf '%s' "$BASE_OUT" | grep -q "repoA-wt"; then
    ok "baseline --list contains repoA-wt (negative control for the mutation)"

    python3 - "$WT" "$HERE/whichtree.mutant.sh" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
anchor = '[ -e "$_d/.git" ] || continue'
assert anchor in text, "anchor vanished between the grep and the rewrite"
open(dst, "w").write(text.replace(anchor, '[ -d "$_d/.git" ] || continue'))
PY

    if [ -f "$HERE/whichtree.mutant.sh" ] && ! diff -q "$WT" "$HERE/whichtree.mutant.sh" >/dev/null 2>&1; then
      ok "mutant differs from the original (the rewrite actually landed)"
      MUT_OUT=$(bash "$HERE/whichtree.mutant.sh" --list 2>&1 || true)
      if printf '%s' "$MUT_OUT" | grep -q "repoA-wt"; then
        bad "MUTANT STILL SEES repoA-wt — the -e/-d distinction is not being tested"
      else
        ok "mutant loses repoA-wt — the worktree test is load-bearing and fenced"
      fi
    else
      bad "mutant was not written, or is identical to the original"
    fi
  else
    bad "baseline --list does NOT contain repoA-wt — fixture broken, mutation vacuous"
  fi
else
  bad "anchor '$ANCHOR' not found in whichtree.sh — did the worktree test change?"
fi

# ── MUTATION 2: revert identity to the remote's last segment ─────────────────
# Without this, the six identity assertions above could all be passing for
# reasons unrelated to wt_ident — a fence that cannot go red proves nothing
# (anti-pattern #71: mutation testing proves SENSITIVITY, never correctness).
echo ""
echo '  ── mutation: wt_ident org/repo  →  last path segment (the original bug)'

ANCHOR2='*/*/*) _u=${_u#"${_u%/*/*}/"} ;;'
if grep -qF -- "$ANCHOR2" "$WT"; then
  ok "identity anchor present before mutating"

  BASE2=$(bash "$WT" --list 2>&1 || true)
  if printf '%s' "$BASE2" | grep -q "shared — MORE THAN ONE"; then
    bad "baseline ALREADY merges the two orgs — the identity fix is not in effect"
  else
    ok "baseline keeps orgOne/shared and orgTwo/shared apart (negative control)"

    python3 - "$WT" "$HERE/whichtree.mutant.sh" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
anchor = '*/*/*) _u=${_u#"${_u%/*/*}/"} ;;'
assert anchor in text, "identity anchor vanished between the grep and the rewrite"
open(dst, "w").write(text.replace(anchor, '*/*/*) _u=${_u##*/} ;;'))
PY

    if [ -f "$HERE/whichtree.mutant.sh" ] && ! diff -q "$WT" "$HERE/whichtree.mutant.sh" >/dev/null 2>&1; then
      MUT2=$(bash "$HERE/whichtree.mutant.sh" --list 2>&1 || true)
      if printf '%s' "$MUT2" | grep -q "shared — MORE THAN ONE"; then
        ok "mutant merges two different orgs — the identity fix is load-bearing"
      else
        bad "MUTANT STILL SEPARATES THEM — the identity assertions test nothing"
      fi
      rm -f "$HERE/whichtree.mutant.sh"
    else
      bad "identity mutant was not written, or is identical to the original"
    fi
  fi
else
  bad "identity anchor not found in whichtree.sh — did wt_ident change?"
fi

echo ""
echo "  $PASS passed · $FAIL failed"
echo ""
if [ "$FAIL" -gt 0 ]; then exit 1; fi
exit 0
