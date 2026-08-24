#!/bin/bash
# Regression fence for the preflight's COMPLETION ASSERTION.
#
# WHY THIS FILE EXISTS. Twice, three months apart, tools/limitless-preflight.sh
# referenced an unbound variable under `set -u`:
#
#   dd10778 (2026-05-18)  ${WARNINGS[*]} inside $( ) — the SUBSHELL died, the
#                         parent survived and exited 0. Labelled "cosmetic",
#                         patched at two literal call sites, class left open.
#   08a2275 (2026-08-23)  $LIMITLESS_STACK_HOME at TOP LEVEL, 172 lines above
#                         its default. Killed checks 4-7 of 7 — and aborted
#                         with status 1, which the preflight's own header
#                         documents as "WARN — session may proceed".
#
# The second one is the dangerous shape: nightly-selfheal.sh maps rc=1 with no
# parseable counts to green=0/yellow=0/red=0, no findings, needs_human=false,
# and titles it "READY* — 0 known-accepted residual (no action)". A watchdog
# reporting all-clear having evaluated nothing. The preflight's own comment
# names the direction: "a false green is believed, a false red is eventually
# investigated."
#
# These tests are the thing that was missing. Run:
#     bash tools/test-preflight-abort.sh          # structural, ~2s
#     bash tools/test-preflight-abort.sh --full   # + one real run, ~60s
#
# Exit 0 = pass, 1 = fail. Test 3 is a NEGATIVE CONTROL: it re-runs the abort
# case with the assertion disabled and REQUIRES the old fail-open behaviour.
# Without it, tests 1/2/4 could all pass on a script where the trap never fires.
set -u

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
PREFLIGHT="$VAULT/tools/limitless-preflight.sh"
PASS=0
FAIL=0

# Clean up by GLOB, not by an accumulated list. The vault path contains a
# space ("…/obsidian /tools"), so a space-joined string of paths word-splits
# into fragments and deletes nothing — observed on this fence's first run.
cleanup() { rm -f "$VAULT"/tools/.preflight-fence-$$-*.sh; }
trap cleanup EXIT

# Mutants are written INTO $VAULT/tools/ (not /tmp) because the preflight
# resolves $VAULT from its own dirname/.. — a copy elsewhere would evaluate a
# different vault. The leading dot keeps them out of the canonical-sync glob.
mutate() {                       # $1 = awk program → prints mutant path
  local m="$VAULT/tools/.preflight-fence-$$-$RANDOM.sh"
  awk "$1" "$PREFLIGHT" > "$m" || return 1
  echo "$m"
}

check() {                        # $1 = name, $2 = ok/notok, $3 = detail
  if [ "$2" = ok ]; then
    PASS=$((PASS + 1)); echo "  ✓ $1"
  else
    FAIL=$((FAIL + 1)); echo "  ✗ $1"; echo "      $3"
  fi
}

# Injected just before the project-manifest block: after the trap installs,
# before any check runs — so the abort cases finish in well under a second.
PROBE='/^# ── Project manifest/ && !p {print ": \"$__ABORT_PROBE_UNSET\""; p=1} {print}'   # unbound-ok: deliberately unset — this string IS the mutation probe
# Same probe, plus the assertion pre-satisfied — i.e. the script as it behaved
# before the fix, with the trap installed but permanently inert.
NOFIX='/^# ── Project manifest/ && !p {print ": \"$__ABORT_PROBE_UNSET\""; p=1}   # unbound-ok: the probe again
       /^PREFLIGHT_COMPLETED=false/ {print "PREFLIGHT_COMPLETED=true"; next} {print}'
# Forces the documented INDETERMINATE path without unplugging the network.
NETAB='/^banner\(\) \{/ && !n {print "NET_STATE=offline"; print "NET_DETAIL=\"fence probe\"";
       print "network_abort fence"; n=1} {print}'

echo ""
echo "preflight completion-assertion fence — $PREFLIGHT"
echo ""

# ── 1. --help must still be a clean exit 0 ──────────────
# (The naive one-flip design broke this: --help exits long before any verdict,
#  so a single flip at the verdict chain turned `--help` into ABORTED/exit 2.)
out=$(bash "$PREFLIGHT" --help 2>&1); rc=$?
if [ "$rc" -eq 0 ] && ! printf '%s' "$out" | grep -q 'ABORTED'; then
  check "--help exits 0 with no ABORTED banner" ok
else
  check "--help exits 0 with no ABORTED banner" notok "got rc=$rc"
fi

# ── 2. a mid-run abort must exit 2 and say so ───────────
m=$(mutate "$PROBE") || { echo "could not build mutant"; exit 1; }
out=$(bash "$m" 2>&1); rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q 'VERDICT: ABORTED'; then
  check "unbound variable mid-run → exit 2 + ABORTED banner" ok
else
  check "unbound variable mid-run → exit 2 + ABORTED banner" notok \
        "got rc=$rc; banner present: $(printf '%s' "$out" | grep -c 'VERDICT: ABORTED')"
fi

# ── 3. NEGATIVE CONTROL — without the fix, the bug returns
# This must FAIL-OPEN: rc=1 (which reads as WARN) and no banner. If this test
# reports the fixed behaviour, the fence is not measuring the assertion at all.
m=$(mutate "$NOFIX") || { echo "could not build mutant"; exit 1; }
out=$(bash "$m" 2>&1); rc=$?
if [ "$rc" -eq 1 ] && ! printf '%s' "$out" | grep -q 'VERDICT: ABORTED'; then
  check "negative control: assertion disabled → exit 1, no banner (the old bug)" ok
else
  check "negative control: assertion disabled → exit 1, no banner (the old bug)" notok \
        "got rc=$rc — the fence is insensitive to the fix; fix the fence first"
fi

# ── 4. INDETERMINATE (rc=3) must survive the trap ───────
# rc=3 exists so a 4am DNS blip is not paged as a BLOCK (2026-07-27). It is
# raised ~1,440 lines above the verdict block, so a careless assertion converts
# it to exit 2 → nightly `*)` → block → needs_human.
m=$(mutate "$NETAB") || { echo "could not build mutant"; exit 1; }
out=$(bash "$m" 2>&1); rc=$?
if [ "$rc" -eq 3 ] && printf '%s' "$out" | grep -q 'INDETERMINATE' \
   && ! printf '%s' "$out" | grep -q 'ABORTED'; then
  check "network_abort still exits 3 as INDETERMINATE, not ABORTED" ok
else
  check "network_abort still exits 3 as INDETERMINATE, not ABORTED" notok "got rc=$rc"
fi

# ── 5. --full: the SUBSHELL variant the trap cannot catch
# The completion assertion closes the fatal/top-level shape only. dd10778 lived
# inside $( ): the subshell dies, the parent completes, the flag flips true and
# the trap never fires (measured — bash 3.2.57, no `set -e` in the preflight).
# The only mechanical tell left is the text bash writes to stderr. This is why
# --full exists; without it the class is closed by half.
if [ "${1:-}" = "--full" ]; then
  echo ""
  echo "  (--full: one real clean-env run, ~60s, posts one lsh_activity row)"
  err=$(mktemp -t preflight-fence-err)
  out=$(env -u LIMITLESS_STACK_HOME bash "$PREFLIGHT" 2>"$err"); rc=$?
  if printf '%s' "$out" | grep -qE 'VERDICT: (READY|WARN|BLOCK)'; then
    check "clean env (LIMITLESS_STACK_HOME unset) reaches a real verdict" ok
  else
    check "clean env (LIMITLESS_STACK_HOME unset) reaches a real verdict" notok "rc=$rc"
  fi
  # Assert on the SHAPE of a bash runtime diagnostic ("<script>: line N: …"),
  # not on the words "unbound variable". Narrowing it to that phrase was my
  # first draft and it passed over two live "integer expression expected"
  # errors from the very block this session was fixing — a `grep -vc || echo 0`
  # producing "0\n0", which made the sibling-repo check fail-silent on a clean
  # repo. One assertion, the whole family.
  if ! grep -qE 'limitless-preflight\.sh: line [0-9]+:' "$err"; then
    check "clean run emits NO bash diagnostics on stderr (subshell variant + kin)" ok
  else
    check "clean run emits NO bash diagnostics on stderr (subshell variant + kin)" notok \
          "$(grep -m3 -E 'limitless-preflight\.sh: line [0-9]+:' "$err")"
  fi
  rm -f "$err"
fi

echo ""
echo "  $PASS passed, $FAIL failed"
echo ""
[ "$FAIL" -eq 0 ] || exit 1
exit 0
