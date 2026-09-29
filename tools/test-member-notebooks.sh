#!/bin/bash
# test-member-notebooks.sh — proves per-person notebooks in a shared vault
# (tools/limitless_member.py + the refresh tool's routing), offline: no NotebookLM calls.
#
# A throwaway vault with an owner (matt), a teammate WITH his own notebooks file (dale)
# and a teammate WITHOUT one (eve). Checks: the owner's view is the manifest unchanged;
# dale gets only his notebooks, his own project first, the owner's projects he doesn't
# carry uploaded NOWHERE (not dumped into his general notebook), records in his own
# folder; eve is refused rather than falling back to the owner's notebooks; a broken
# file and an unreadable identity behave as documented. Then a NEGATIVE CONTROL: the
# same cases against a copy whose swap is disabled must fail.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3.11 || command -v python3)"
W="$(mktemp -d "${TMPDIR:-/tmp}/membernb.XXXXXX")" || exit 2; [ -n "$W" ] || exit 2; trap 'rm -rf "$W"' EXIT
PASS=0; FAILN=0
ok()  { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad() { echo "  ✗ $1"; FAILN=$((FAILN+1)); }
check() { local label="$1" want="$2" got="$3"; [ "$got" = "$want" ] && ok "$label" || bad "$label (want '$want', got '$got')"; }

V="$W/vault "   # ends in a space on purpose, like the shared vault
build() {   # $1 = the limitless_member.py to install
  rm -rf "$V"; mkdir -p "$V/tools" "$V/wiki/apps" "$V/wiki/synthesis" "$V/wiki/concepts" "$V/members/dale"
  cp "$HERE/notebooklm-wiki-refresh.py" "$HERE/authorship-guard.py" "$V/tools/"
  cp "$1" "$V/tools/limitless_member.py"
  cat > "$V/.limitless-project.py" <<'EOF'
PROJECT_ID = "t"
VAULT_OWNER = "matt"
NOTEBOOKLM = {
    "routes": [
        ("wiki/apps/alpha.md", "AAAA", "alpha", "Alpha"),
        ("wiki/apps/beta.md", "BBBB", "beta", "Beta"),
        ("wiki/synthesis/beta-", "BBBB", "beta", "Beta"),
    ],
    "default": ("DDDD", "wiki", "wiki"),
    "reminder": {"notebook_id": "RRRR", "files": ["CLAUDE.md"]},
}
EOF
  printf '{"people": {"matt": {"emails": ["matt@example.com"]}, "dale": {"emails": ["dale@example.com"]}, "eve": {"emails": ["eve@example.com"]}}}\n' > "$V/.authors.json"
  cat > "$V/members/dale/notebooklm.py" <<'EOF'
NOTEBOOKS = {"reminder": "dR", "wiki": "dW", "alpha": "dA", "mine": "dM"}
OWN_ROUTES = [("wiki/apps/mine.md", "mine", "Mine")]
IGNORED = {"dX": "someone else's"}
EOF
  for f in apps/alpha.md apps/beta.md synthesis/beta-x.md apps/mine.md concepts/general.md; do echo "# $f" > "$V/wiki/$f"; done
  echo "# rules" > "$V/CLAUDE.md"
  touch -t 202601010000 "$V/wiki/concepts/general.md"; touch -t 202601020000 "$V/wiki/apps/mine.md"
  touch -t 202601030000 "$V/wiki/apps/alpha.md"; touch -t 202601040000 "$V/wiki/apps/beta.md"
  touch -t 202601050000 "$V/wiki/synthesis/beta-x.md"
  git -C "$V" init -q
}
as() { local email="$1"; shift; GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.email GIT_CONFIG_VALUE_0="$email" "$@"; }
view() {   # $1 email -> "role|state dir (relative)|route labels|default|reminder|skipped labels"
  as "$1" "$PY" - "$V" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1] + "/tools")
from pathlib import Path
import limitless_member as lm
try:
    nb, sd, info = lm.resolve(sys.argv[1])
except ValueError:
    print("invalid"); sys.exit()
labels = ",".join(sorted({r[2] + "=" + r[1] for r in nb.get("routes", [])}))
skipped = ",".join(sorted({o[3] for o in nb.get("routing_order", []) if o[2] is None}))
print("|".join([info["role"], str(Path(sd).relative_to(Path(sys.argv[1]))), labels,
                (nb.get("default") or ("",))[0], (nb.get("reminder") or {}).get("notebook_id", ""), skipped]))
EOF
}
count() { as "$1" "$PY" "$V/tools/notebooklm-wiki-refresh.py" --count-routed "$2" 2>/dev/null; }

run_cases() {
  build "$1"
  check "owner: the manifest's notebooks, records in tools/" \
        "owner|tools|alpha=AAAA,beta=BBBB|DDDD|RRRR|" "$(view matt@example.com)"
  check "teammate: only his notebooks, his own project, records in his folder" \
        "member|members/dale/notebooklm-state|alpha=dA,mine=dM|dW|dR|Beta" "$(view dale@example.com)"
  check "teammate without a notebooks file: none at all (never the owner's)" "unset|members/eve/notebooklm-state||||" "$(view eve@example.com)"
  check "no commit email: treated as the owner (fail-open)" "owner|tools|alpha=AAAA,beta=BBBB|DDDD|RRRR|" "$(view '')"
  check "email not in .authors.json: no notebooks" "unset|members/unknown <who@example.com>/notebooklm-state||||" "$(view who@example.com)"
  check "owner: beta gets both beta pages" "2" "$(count matt@example.com beta)"
  check "owner: general notebook gets the unrouted pages" "2" "$(count matt@example.com wiki)"
  check "teammate: a project he doesn't carry is uploaded nowhere" "0" "$(count dale@example.com beta)"
  check "teammate: its pages are NOT dumped into his general notebook" "1" "$(count dale@example.com wiki)"
  check "teammate: his own project gets its page" "1" "$(count dale@example.com mine)"
  check "teammate: a shared project gets its page" "1" "$(count dale@example.com alpha)"
  gen=$(stat -f '%m' "$V/wiki/concepts/general.md" 2>/dev/null || stat -c '%Y' "$V/wiki/concepts/general.md")
  check "teammate: newest page in his general notebook ignores other routes" "$gen" \
        "$(as dale@example.com "$PY" "$V/tools/notebooklm-wiki-refresh.py" --newest-routed wiki 2>/dev/null)"
  as eve@example.com "$PY" "$V/tools/notebooklm-wiki-refresh.py" --count-routed wiki >/dev/null 2>&1
  check "teammate without notebooks: the refresh refuses (exit 2)" "2" "$?"
  printf 'NOTEBOOKS = {"wiki": "dW"}\n' > "$V/members/dale/notebooklm.py"
  check "a notebooks file with no reminder notebook is reported, not guessed" "invalid" "$(view dale@example.com)"
  as dale@example.com "$PY" "$V/tools/notebooklm-wiki-refresh.py" --count-routed wiki >/dev/null 2>&1
  check "…and the refresh refuses it (exit 2)" "2" "$?"
}

echo "per-person notebooks — cases"
run_cases "$HERE/limitless_member.py"
REAL_PASS=$PASS; REAL_FAIL=$FAILN

echo "negative control — a copy with the swap disabled must be caught"
sed 's/^    if not teammate:$/    if True:  # MUTANT/' "$HERE/limitless_member.py" > "$W/mutant.py"
grep -q "MUTANT" "$W/mutant.py" || { echo "  ✗ could not build the mutant"; exit 2; }
FAILN=0
run_cases "$W/mutant.py" >/dev/null
MUT_RED=$FAILN; PASS=$REAL_PASS; FAILN=$REAL_FAIL
if [ "$MUT_RED" -gt 0 ]; then ok "the tests catch a disabled swap ($MUT_RED cases went red)"; else bad "a disabled swap passed every case — the tests cannot fail"; fi

echo ""
echo "  $PASS passed, $FAILN failed"
[ "$FAILN" -eq 0 ]
