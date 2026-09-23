#!/bin/bash
# test-authorship-guard.sh — proves tools/authorship-guard.py enforces the shared-vault rule:
# anyone may ADD; only the author may change or remove their own writing; path-owned files
# (members/<login>/, wiki/my-tasks/<login>.md) belong to one person outright.
#
# Builds a throwaway repo with two people ("matt", "dale"), runs every case, then a NEGATIVE
# CONTROL: the same "must block" cases against a copy of the guard with its check disabled
# must FAIL — otherwise these tests could not detect a broken guard.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/authorship-guard.py"
PY="$(command -v python3.11 || command -v python3)"
W="$(mktemp -d "${TMPDIR:-/tmp}/apguard.XXXXXX")" || exit 2; [ -n "$W" ] || exit 2; trap 'rm -rf "$W"' EXIT
PASS=0; FAILN=0
G=""   # the guard under test; run_cases sets it (declared here for set -u)
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAILN=$((FAILN+1)); }

as_matt() { git -c user.name=Matt -c user.email=matt@example.com "$@"; }
as_dale() { git -c user.name=Dale -c user.email=dale@example.com "$@"; }
as_stranger() { git -c user.name=Who -c user.email=who@example.com "$@"; }

R="$W/vault "   # the folder name ends in a SPACE on purpose — the shared vault's does
setup() {
  rm -rf "$R"; mkdir -p "$R"; cd "$R"; git init -q
  cat > .authors.json <<'EOF'
{"people": {"matt": {"emails": ["matt@example.com"]}, "dale": {"emails": ["dale@example.com"]}},
 "exempt_paths": ["tools/.notebooklm-*-state.json"],
 "exempt_line_patterns": ["^updated: "]}
EOF
  mkdir -p wiki/my-tasks tools members/dale
  printf -- '---\nupdated: 2026-01-01\n---\nmatt line 1\nmatt line 2\n' > wiki/page.md
  printf '{"a": 1}\n' > tools/.notebooklm-wiki-state.json
  printf 'intro\n<!-- BEGIN GENERATED INDEX -->\ngen 1\n<!-- END GENERATED -->\n' > wiki/ap.md
  printf 'matt task\n' > wiki/my-tasks/matt.md
  as_matt add -A && as_matt commit -qm "matt base"
  printf 'dale line 1\n' >> wiki/page.md
  printf 'dale task\n' > wiki/my-tasks/dale.md
  printf 'dale rules\n' > members/dale/CLAUDE.md
  printf 'dale entry\n' >> wiki/ap.md
  printf 'caf\351 \223quoted\224\n' > wiki/latin1.md          # not UTF-8, on purpose
  printf '\x89PNG\r\n\x1a\n\x00\x01binary' > wiki/dale.png   # a binary file Dale added
  as_dale add -A && as_dale commit -qm "dale adds"
}
# run the guard on the STAGED change as a given identity; echo exit code
staged() { local who="$1"; shift; "$who" config user.email >/dev/null 2>&1
  local email; case "$who" in as_matt) email=matt@example.com;; as_dale) email=dale@example.com;; *) email=who@example.com;; esac
  git -c user.email="$email" -c user.name=x add -A >/dev/null
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.email GIT_CONFIG_VALUE_0="$email" "$PY" "$G" --staged >/dev/null 2>&1; echo $?; }
expect() { local label="$1" want="$2" got="$3"; [ "$got" = "$want" ] && ok "$label" || bad "$label (want exit $want, got $got)"; git reset -q --hard; }

run_cases() {
  G="$1"
  setup
  echo "matt adds" >> wiki/page.md;                         expect "anyone may ADD lines to a shared page" 0 "$(staged as_matt)"
  sed -i.b 's/matt line 1/matt line ONE/' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "author may change their OWN line" 0 "$(staged as_matt)"
  sed -i.b 's/dale line 1/dale line EDITED/' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "BLOCK: changing someone else's line" 1 "$(staged as_matt)"
  sed -i.b '/dale line 1/d' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "BLOCK: deleting someone else's line" 1 "$(staged as_matt)"
  echo "matt note" >> wiki/my-tasks/dale.md;                expect "BLOCK: writing into someone else's task file" 1 "$(staged as_matt)"
  echo "more" >> members/dale/CLAUDE.md;                    expect "BLOCK: writing into someone else's members/ CLAUDE.md" 1 "$(staged as_matt)"
  echo "dale more" >> wiki/my-tasks/dale.md;                expect "owner may write their own task file" 0 "$(staged as_dale)"
  git rm -q wiki/my-tasks/dale.md;                          expect "BLOCK: deleting someone else's task file" 1 "$(staged as_matt)"
  sed -i.b 's/^updated: .*/updated: 2026-09-23/' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "exempt: bumping a page's updated: date" 0 "$(staged as_dale)"
  printf '{"a": 2}\n' > tools/.notebooklm-wiki-state.json;  expect "exempt: machine-written state file" 0 "$(staged as_dale)"
  sed -i.b 's/gen 1/gen 2/' wiki/ap.md; rm -f wiki/ap.md.b; expect "exempt: regenerating a GENERATED block" 0 "$(staged as_dale)"
  sed -i.b 's/matt line 2/stranger/' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "BLOCK: unknown identity changing a line" 1 "$(staged as_stranger)"
  echo "new file" > wiki/new.md;                            expect "anyone may ADD a new file" 0 "$(staged as_dale)"
  printf 'rewritten\n' > wiki/latin1.md;                     expect "non-UTF-8 text does not crash the check" 0 "$(staged as_dale)"
  printf 'rewritten\n' > wiki/latin1.md;                     expect "BLOCK: rewriting someone else's non-UTF-8 line" 1 "$(staged as_matt)"
  printf 'x' >> wiki/dale.png;                              expect "BLOCK: changing a binary file someone else added" 1 "$(staged as_matt)"
  printf 'x' >> wiki/dale.png;                              expect "owner may change their own binary file" 0 "$(staged as_dale)"
  sed -i.b 's/matt line 1/dale rewrote/' wiki/page.md; rm -f wiki/page.md.b
  as_dale add -A; as_dale commit -qm "dale rewrites matt" --no-verify
  "$PY" "$G" --commit HEAD >/dev/null 2>&1;                 expect "CI mode: finds a violation that skipped the hook" 1 "$?"
  "$PY" "$G" --commit HEAD~1 >/dev/null 2>&1;               expect "CI mode: a clean commit passes" 0 "$?"
  rm -f .authors.json; as_matt add -A; as_matt commit -qm "no config" -q
  sed -i.b 's/dale line 1/x/' wiki/page.md; rm -f wiki/page.md.b
                                                             expect "opt-in: no .authors.json means no checks" 0 "$(staged as_matt)"
}

echo "authorship guard — cases"
run_cases "$GUARD"
REAL_FAIL=$FAILN

echo "negative control — guard with its check disabled must be caught"
sed 's/^    violations = \[\]$/    return []  # MUTANT/' "$GUARD" > "$W/mutant.py"
grep -q "MUTANT" "$W/mutant.py" || { echo "  ✗ could not build the mutant"; exit 2; }
REAL_PASS=$PASS; FAILN=0
run_cases "$W/mutant.py" >/dev/null
MUT_RED=$FAILN; PASS=$REAL_PASS; FAILN=$REAL_FAIL
if [ "$MUT_RED" -gt 0 ]; then ok "the tests catch a disabled guard ($MUT_RED cases went red)"; else bad "a disabled guard passed every case — the tests cannot fail"; fi

echo ""
echo "  $PASS passed, $FAILN failed"
[ "$FAILN" -eq 0 ]
