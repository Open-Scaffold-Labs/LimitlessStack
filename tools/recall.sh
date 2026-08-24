#!/bin/bash
# recall.sh — the Limitless Stack's RETRIEVAL layer.
#
# WHY THIS EXISTS. The stack stores in four places and had no retrieval
# discipline. The measured failure mode is NOT missing history — it is QUERY
# FORMULATION: sessions search for the ARTIFACT NAME (a branch, a gameplan, a
# file) and never for the SUBJECT (what the thing is about). Three documented
# occurrences, two of them repeats of each other:
#   wiki/log.md:157   searched `fix/fi-department-scoping`; never `station_id`
#   wiki/log.md:8306  searched the gameplan; never `companion` / form factor
#   wiki/log.md:8333  "The Stack held the facts and still could not deliver them"
# The decisive query in the first was measured at NINE SECONDS.
#
# USAGE
#   tools/recall.sh <subject-noun> [more nouns...]     # nouns are OR-ed
#   tools/recall.sh --top 40 licensing dept_id
#
# EXIT CODES — three states, deliberately distinguishable:
#   0  hits found.
#   1  searched successfully, ZERO hits. This usually means the WRONG NOUN,
#      not absent history. It is NOT a licence to conclude anything.
#   2  the search did not actually run (empty corpus / unreadable files).
#      An empty result is only meaningful if the search RAN — anti-pattern #42.
#      Never let 1 and 2 collapse into each other; that is the false-green shape
#      that let the nightly report READY over an unmeasured set (2026-08-24).
#
# `set -u` is on and EVERY variable is assigned above its first use. The
# preflight shipped a use-before-define under set -u on 2026-08-23 and it killed
# 4 of 7 checks (anti-pattern #72). Do not reintroduce that shape here. Note
# also: under bash 3.2 a DECLARED-but-EMPTY array still explodes under set -u,
# so array reads below are count-guarded, never bare.

set -u

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
# FOUND, not guessed. Two revisions on 2026-08-24: hardcoded (which made the
# empty-corpus path untestable — a fake vault still picked the absolute path up,
# so exit 2 never once ran, anti-pattern #54), then an overridable default, which
# Matt correctly called a guess with a seatbelt: if nobody exports the variable —
# every shell on every other machine — it lands on the Mac path anyway.
# Now it searches, takes the first candidate that really is the Hub's CLAUDE.md,
# and falls back only as the LAST item in that search. Still overridable, so the
# empty-corpus test stays possible.
_find_hub_claude() {
  local _c
  # An EXPLICIT override wins outright — even when it points at nothing. The
  # first version of this search treated it as merely the first candidate and
  # searched PAST it when the file was absent, which silently re-found the real
  # Hub and broke the empty-corpus test (exit 2 → 0). An override that only
  # holds when it happens to be valid is not an override.
  if [ -n "${RECALL_HUB_CLAUDE:-}" ]; then printf '%s' "${RECALL_HUB_CLAUDE:-}"; return 0; fi
  for _c in "$HOME/limitless-stack-hub/CLAUDE.md" \
            "$(dirname "$VAULT")/limitless-stack-hub/CLAUDE.md" \
            "$(dirname "$(dirname "$VAULT")")/limitless-stack-hub/CLAUDE.md"; do
    [ -n "$_c" ] && [ -f "$_c" ] && { printf '%s' "$_c"; return 0; }
  done
  printf '%s' "${RECALL_HUB_CLAUDE:-$HOME/limitless-stack-hub/CLAUDE.md}"
}
HUB_CLAUDE="$(_find_hub_claude)"
COUNTER="$VAULT/tools/.recall-counter.tsv"
TOP=25
NOUN_COUNT=0
NOUNS=()
FILES_SEARCHED=0
LINES_SEARCHED=0
TOTAL_HITS=0
PATTERN=""
# Assigned in the log block below; declared HERE so the closing summary can read
# it under `set -u` no matter which branches ran. Referencing it before this line
# is the use-before-define shape of anti-pattern #72 — which was reintroduced
# into THIS FILE while writing the closing summary on 2026-08-24, third time in
# one session. Declare first, assign later, never the reverse.
LOG_SPAN=""

usage() {
  echo "usage: tools/recall.sh [--top N] <subject-noun> [more nouns...]"
  echo ""
  echo "  Search the Stack's history by SUBJECT, not by artifact name."
  echo "  Good:  recall.sh companion          recall.sh station_id tenant"
  echo "  Bad:   recall.sh fix/my-branch-name  (an artifact name finds nothing)"
  echo ""
  echo "  exit 0 = hits · 1 = searched, none found · 2 = search did not run"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --top)   shift; TOP="${1:-25}" ;;
    --top=*) TOP="${1#*=}" ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "recall: unknown flag '$1'" >&2; usage >&2; exit 2 ;;
    *)  NOUNS+=("$1"); NOUN_COUNT=$((NOUN_COUNT+1)) ;;
  esac
  shift
done

if [ "$NOUN_COUNT" -eq 0 ]; then
  echo "recall: no subject noun given — nothing was searched." >&2
  usage >&2
  exit 2
fi

# Build a lowercased alternation. Count-guarded read (bash 3.2 + set -u).
for _n in "${NOUNS[@]}"; do   # unbound-ok: NOUN_COUNT -eq 0 exits 2 above, so NOUNS is non-empty here
  _lc="$(printf '%s' "$_n" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$PATTERN" ]; then PATTERN="$_lc"; else PATTERN="$PATTERN|$_lc"; fi
done

# ── Corpus ──────────────────────────────────────────────
# log.md is searched with entry-heading awareness (a bare line number does not
# tell you WHEN a ruling was made or what it was about). Everything else is a
# plain numbered grep.
LOG="$VAULT/wiki/log.md"
FLAT_FILES=""
for _f in "$VAULT/CLAUDE.md" \
          "$HUB_CLAUDE" \
          "$VAULT/wiki/synthesis/claude-anti-patterns.md" \
          "$VAULT/wiki/team-tasks.md" \
          "$VAULT"/wiki/my-tasks/*.md; do
  [ -r "$_f" ] && FLAT_FILES="$FLAT_FILES$_f
"
done

count_lines() { wc -l < "$1" 2>/dev/null | tr -d ' '; }

[ -r "$LOG" ] && {
  FILES_SEARCHED=$((FILES_SEARCHED+1))
  LINES_SEARCHED=$((LINES_SEARCHED + $(count_lines "$LOG")))
}
while IFS= read -r _f; do
  [ -z "$_f" ] && continue
  FILES_SEARCHED=$((FILES_SEARCHED+1))
  LINES_SEARCHED=$((LINES_SEARCHED + $(count_lines "$_f")))
done <<EOF
$FLAT_FILES
EOF

# POSITIVE CONTROL. A zero-hit answer is worthless if the corpus was empty.
if [ "$FILES_SEARCHED" -eq 0 ] || [ "$LINES_SEARCHED" -eq 0 ]; then
  echo "recall: CORPUS EMPTY — $FILES_SEARCHED file(s), $LINES_SEARCHED line(s)." >&2
  echo "        The search did NOT run. This is exit 2, not 'no history'." >&2
  echo "        Check VAULT=$VAULT" >&2
  exit 2
fi

echo "━━ recall: $PATTERN"
echo "   searched $FILES_SEARCHED file(s) · $LINES_SEARCHED line(s)   [positive control]"
echo ""

# ── wiki/log.md, grouped under the entry heading that owns each hit ──────
# NOTE: wiki/log.md is NOT stored in date order — its first 67 entries run
# newest-first and then it flips to ascending; 30 backward date transitions
# across 609 entries (re-derived 2026-08-24; an earlier draft of this comment
# said "~51", a figure inherited from a subagent and never checked).
# So file order must never be presented as chronology. Hits are re-sorted by the
# entry's own date, NEWEST FIRST, because a later ruling supersedes an earlier
# one and that is the hit a session needs to see first.
LOG_HITS=0
if [ -r "$LOG" ]; then
  LOG_HITS="$(awk -v pat="$PATTERN" 'tolower($0) ~ pat { n++ } END { print n+0 }' "$LOG")"
  if [ "$LOG_HITS" -gt 0 ]; then
    # Entry count + date span: the two things about a result set that CAN be
    # stated as fact. 7 hits over 4 entries across two months reads very
    # differently from 51 over 29, and the reader should see that before judging.
    LOG_SPAN="$(awk -v pat="$PATTERN" '
        /^## \[/ { d = ""
          if (match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/))
            d = substr($0, RSTART, RLENGTH)
          hdr = $0
        }
        tolower($0) ~ pat {
          if (hdr != seen) { c++; seen = hdr
            if (d != "") { if (lo == "" || d < lo) lo = d; if (d > hi) hi = d }
          }
        }
        END {
          if (c > 0) printf " in %d log entry(s), %s → %s", c, (lo=="" ? "?" : lo), (hi=="" ? "?" : hi)
        }' "$LOG")"
    echo "wiki/log.md — $LOG_HITS hit(s) in $(awk -v pat="$PATTERN" '
        /^## \[/ { hdr = $0 }
        tolower($0) ~ pat { if (hdr != seen) { c++; seen = hdr } }
        END { print c+0 }' "$LOG") entry(s)   [NEWEST FIRST]"
    awk -v pat="$PATTERN" '
      /^## \[/ {
        hdr = $0; d = "0000-00-00"
        if (match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/))
          d = substr($0, RSTART, RLENGTH)
        next
      }
      tolower($0) ~ pat {
        line = $0; gsub(/^[ \t]+/, "", line)
        if (length(line) > 150) line = substr(line, 1, 150) "…"
        printf "%s\t%s\t%d\t%s\n", d, (hdr == "" ? "(preamble)" : hdr), NR, line
      }' "$LOG" \
    | sort -r -t"$(printf '\t')" -k1,1 -k3,3n \
    | awk -F"$(printf '\t')" -v top="$TOP" '
        $2 != last { groups++; if (groups > top) exit; printf "\n  %s\n", $2; last = $2; shown = 0 }
        groups <= top && shown < 3 { printf "      %d: %s\n", $3, $4; shown++ }'
    echo ""
  fi
  TOTAL_HITS=$((TOTAL_HITS + LOG_HITS))
fi

# ── trust anchors + task files ───────────────────────────
while IFS= read -r _f; do
  [ -z "$_f" ] && continue
  # NOT `|| echo 0`: grep -c already PRINTS 0 and then exits 1, so the fallback
  # appends a second line and every integer test downstream errors on "0\n0".
  # This is the exact shape anti-pattern #72's corrective names — reproduced
  # here on 2026-08-24 while writing this file, and caught by running it.
  _n="$(grep -ic -E "$PATTERN" "$_f" 2>/dev/null || true)"
  _n="${_n:-0}"
  [ "$_n" -eq 0 ] && continue
  echo "${_f#$VAULT/} — $_n hit(s)"
  grep -in -E "$PATTERN" "$_f" 2>/dev/null | head -6 | cut -c1-170 | sed 's/^/      /'
  echo ""
  TOTAL_HITS=$((TOTAL_HITS + _n))
done <<EOF
$FLAT_FILES
EOF

# ── Verdict ──────────────────────────────────────────────
if [ "$TOTAL_HITS" -eq 0 ]; then
  echo "0 hits for \"$PATTERN\"."
  echo ""
  echo "🔴 A ZERO HERE USUALLY MEANS THE WRONG NOUN, NOT ABSENT HISTORY."
  echo "   The corpus WAS searched ($FILES_SEARCHED files, $LINES_SEARCHED lines)."
  echo "   The documented failure is searching an ARTIFACT NAME — a branch, a"
  echo "   gameplan, a filename — instead of the SUBJECT it is about."
  echo ""
  echo "   Ask: what is this thing ABOUT? Then search that."
  echo "     a branch about tenancy      → station_id · department_id · tenant"
  echo "     a spec about screen size    → form factor · viewport · companion"
  echo "     a migration about roles     → readonly · grant · RLS · role"
  echo ""
  echo "   Do NOT conclude 'this was never decided' on the strength of this run."
  exit 1
fi

# Self-instrumentation: record only PRODUCTIVE runs, so in 30 days this tool can
# answer "did I earn my keep?" — the question no other safeguard here can answer
# about itself (the fabrication scanner ran 4 months at zero catches unnoticed).
{
  printf '%s\t%s\t%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PATTERN" "$TOTAL_HITS" "$FILES_SEARCHED"
} >> "$COUNTER" 2>/dev/null || true

echo "$TOTAL_HITS hit(s)$LOG_SPAN. Listed NEWEST FIRST — start at the top, because a"
echo "later ruling supersedes an earlier one. (log.md is NOT stored chronologically;"
echo "these were re-sorted by each entry's own date.)"
echo ""
echo "⚠ REQUIRED before you conclude anything: are these hits ABOUT your subject,"
echo "  or do they merely MENTION it? An artifact name — a branch, a gameplan, a"
echo "  filename — matches incidentally all over the corpus and proves nothing."
echo "  If none of these entries is a RULING about the thing itself, you searched"
echo "  the wrong noun. Search what it is ABOUT and run again."
echo ""
echo "  This warning is unconditional on purpose. No heuristic reliably separates"
echo "  'about it' from 'mentions it' — both candidates were tested on real data"
echo "  2026-08-24 and both passed the known-bad control. The discrimination is"
echo "  yours to make; the tool's job is to stop you skipping it."
exit 0
