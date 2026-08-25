#!/bin/bash
# whichtree.sh — resolve a BARE repo-relative path to the working tree(s) that hold it.
#
# WHY THIS EXISTS. On 2026-08-24 a session disputed a CORRECT citation
# (`client/src/design/tokens.css`) by resolving it from memory to the wrong tree,
# and nearly filed a false finding against a reader whose evidence was exact
# (wiki/log.md:11346). The same night's fix shipped the routing line "cite a repo
# with every path" and recorded the residue plainly:
#
#     "Not fixed, stated plainly: the second trap — resolving a relative path to
#      the wrong repo — has no mechanical guard."   (wiki/log.md:11381)
#
# Matt's ruling: a bare path is ambiguous ONLY because nothing resolves it, and
# resolving it is a `find` across the trees we already enumerate. This is that.
#
# USAGE
#   tools/whichtree.sh <bare/path> [more paths...]   # resolve citations
#   tools/whichtree.sh --list                        # the multi-tree routing block
#   tools/whichtree.sh --help
#
# A trailing :LINE or :LINE:COL is stripped, so a citation pastes verbatim:
#   tools/whichtree.sh client/src/design/tokens.css:127
# A leading <repo>/ is also tolerated — the convention this tool enforces is
# `<repo>/<file>:<line>`, so a correctly-formatted citation MUST resolve. If the
# path does not exist as given, one leading segment is stripped and retried.
#
# EXIT CODES — five states, deliberately distinguishable.
#   0  every path resolved to exactly ONE tree. The citation is unambiguous.
#   1  usage error.
#   2  THE SCAN DID NOT RUN — zero working trees enumerated. An empty answer is
#      only meaningful if the search RAN (anti-pattern #42). Never let this
#      collapse into 3; that is the false-green shape.
#   3  at least one path matched ZERO trees.
#   4  at least one path matched MORE THAN ONE tree — AMBIGUOUS, resolve before
#      citing. This is the state the tool was built for.
#   5  at least one path was cited as `<repo>/<file>` where that repo DOES NOT
#      hold it, but another tree does — MISATTRIBUTED. This is the exact shape of
#      the 2026-08-24 bug and it is the loudest state on purpose.
#   Precedence when several apply: 2 > 5 > 4 > 3.
#
# THE UNIT IS A WORKING TREE OF A REPO NAMED BY ITS REMOTE — not a directory.
# `Open-Scaffold-Labs/OpenFirehouse-private` has FOUR trees under $HOME;
# `paperclip` has FOUR. Calling a directory "a repo" is what produced the bug.
#
# RANKING IS LOCAL AND FETCH-INDEPENDENT: newest HEAD commit date wins. Do NOT
# rank by `rev-list HEAD..origin/main` — that reads the tree's OWN origin/main
# ref, only as fresh as its last fetch, so an unfetched clone reports itself
# current and lies. openfirehouse-phase4 claimed CURRENT at migration 0115 while
# neris was at 0143.
#
# `set -u` is on and EVERY variable is assigned above its first use. The preflight
# shipped a use-before-define under set -u on 2026-08-23 and it killed 4 of 7
# checks (anti-pattern #72). Do not reintroduce that shape here.

set -u

# Overridable, never hardcoded — an unconditional machine path degrades to a
# polite "can't check that here" on every other machine, and it also makes the
# exit-2 branch untestable (anti-pattern #54: a probe that cannot fail).
WT_HOME="${WT_HOME:-$HOME}"
WT_MAXDEPTH="${WT_MAXDEPTH:-4}"

wt_usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

# ── REPO IDENTITY ──────────────────────────────────────────────────────────────
# The identity is the REMOTE, and "the remote" is not its last path segment.
# Measured on this Mac 2026-08-24, the last-segment form is wrong in BOTH
# directions at once:
#
#   SPLITS what is one repo   https://github.com/Open-Scaffold-Labs/OpenFirehouse-private.git
#                             https://mlav1114@github.com/Open-Scaffold-Labs/OpenFirehouse-private.git
#                             — identical repo, one carries a credential prefix.
#
#   MERGES what are two       https://github.com/Open-Scaffold-Labs/paperclip.git
#                             https://github.com/paperclipai/paperclip.git
#                             — DIFFERENT UPSTREAMS. The routing block was ranking
#                               a vendor checkout against ours as "older", which is
#                               a false instruction about which tree to read.
#
# So: strip scheme, strip user@ credentials, fold scp-style `host:org/repo` to a
# path, drop `.git`, and keep `org/repo` as the identity. That separates the two
# paperclips and merges the two OpenFirehouse-private URLs.
wt_ident() {
  local _u="$1"
  _u=${_u%/}
  _u=${_u%.git}
  _u=${_u#*://}          # drop scheme:// if present
  _u=${_u#*@}            # drop user@ credentials (also strips git@ in scp form)
  case "$_u" in
    */*:*) : ;;                    # colon after a slash — a port or a path; leave it
    *:*)   _u=${_u/:/\/} ;;        # scp-style host:org/repo -> host/org/repo
  esac
  # Keep the last two segments: org/repo. The host is dropped because every
  # remote here is one host; if that ever stops being true, keep three.
  case "$_u" in
    */*/*) _u=${_u#"${_u%/*/*}/"} ;;
  esac
  printf '%s' "$_u"
}

# ── THE ONE ENUMERATION ────────────────────────────────────────────────────────
# limitless-preflight.sh's WHICH WORKING TREE block calls `--list` rather than
# repeating this loop. Two evaluators of "which trees exist" would drift, and
# this vault has caught that disease three times (anti-pattern #46). If you need
# tree data anywhere else, call this script — do not copy the loop.
#
# Emits TSV: slug \t head_ts \t relpath \t branch \t migration_suffix \t abspath
wt_enumerate() {
  local _g _d _rem _slug _ts _br _mig _rel
  while IFS= read -r _g; do
    [ -n "$_g" ] || continue
    _d=${_g%/.git}
    # -e not -d: a git WORKTREE's .git is a FILE ("gitdir: ..."), not a directory.
    # The `-d` form silently skipped openfirehouse-neris — the ONE tree holding
    # current code — and would have routed sessions away from migration 0143.
    [ -e "$_d/.git" ] || continue
    _rem=$(git -C "$_d" remote get-url origin 2>/dev/null) || continue
    [ -n "$_rem" ] || continue
    _slug=$(wt_ident "$_rem")
    [ -n "$_slug" ] || continue
    _ts=$(git -C "$_d" log -1 --format=%ct 2>/dev/null) || continue
    [ -n "$_ts" ] || continue
    _br=$(git -C "$_d" branch --show-current 2>/dev/null)
    if [ -z "$_br" ]; then _br="DETACHED"; fi
    _mig=$(ls "$_d"/docs/migrations/*.sql 2>/dev/null | sed 's|.*/||' | sort -t- -k1,1n | tail -1)
    _mig=${_mig%%-*}
    if [ -n "$_mig" ]; then _mig=" · migration $_mig"; else _mig=""; fi
    _rel=${_d#"$WT_HOME"/}
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$_slug" "$_ts" "$_rel" "$_br" "$_mig" "$_d"
  done < <(find "$WT_HOME" -maxdepth "$WT_MAXDEPTH" \
             \( -name node_modules -o -name Library -o -name .Trash \) -prune -o \
             -name .git -print 2>/dev/null)
}

# ── --list : the routing block the preflight prints ────────────────────────────
# Only groups with MORE THAN ONE tree are printed — a single-tree repo has no
# ambiguity to warn about, and this block is routing, not a wall of inventory.
wt_list() {
  local _rows _multi _g _groups
  _rows=$(wt_enumerate)
  if [ -z "$_rows" ]; then
    echo "  • working trees      ⊘ none found under \$WT_HOME — cannot say which tree is current"
    return 2
  fi
  _groups=0
  _multi=$(printf '%s\n' "$_rows" | cut -f1 | sort | uniq -d)
  for _g in $_multi; do
    _groups=$((_groups + 1))
    echo "  • $_g — MORE THAN ONE WORKING TREE:"
    printf '%s\n' "$_rows" | awk -F'\t' -v g="$_g" '$1==g' \
      | sort -t"$(printf '\t')" -k2,2nr \
      | awk -F'\t' 'NR==1{printf "      %-34s ✅ NEWEST  (%s)%s\n",$3,$4,$5; next}
                     {printf "      %-34s ⚠ older    (%s)%s\n",$3,$4,$5}'
  done
  if [ "$_groups" -eq 0 ]; then
    echo "  • working trees      every repo has exactly one tree — no ambiguity to resolve"
  else
    echo "                      → Ranked by HEAD commit DATE, locally. Not by origin/main:"
    echo "                        an unfetched clone reports itself current and lies."
    echo "                      → Read NEWEST. A stale tree makes shipped work look unbuilt."
    echo "                      → Cite the REPO with every path: <repo>/<file>:<line>."
    echo "                        Unsure which tree a path is in? tools/whichtree.sh <path>"
  fi
  return 0
}

# ── default : resolve each argument ────────────────────────────────────────────
wt_resolve() {
  local _rows _n _worst _arg _p _stripped _hits _count _prefix _claimed
  _rows=$(wt_enumerate)
  _n=$(printf '%s' "$_rows" | grep -c . || true)
  [ -n "$_n" ] || _n=0

  echo "━━ whichtree: scanned $_n working tree(s) under $WT_HOME   [positive control]"
  echo ""
  if [ "$_n" -eq 0 ]; then
    echo "🔴 THE SCAN DID NOT RUN — zero working trees enumerated."
    echo "   Every answer below would be an artifact of that, not a fact about the path."
    echo "   Check \$WT_HOME (currently: $WT_HOME) and \$WT_MAXDEPTH (currently: $WT_MAXDEPTH)."
    return 2
  fi

  _worst=0
  for _arg in "$@"; do
    # Strip a trailing :LINE or :LINE:COL so a citation pastes verbatim.
    _p=$(printf '%s' "$_arg" | sed -E 's/:[0-9]+(:[0-9]+)?$//')
    _p=${_p#./}
    echo "  $_arg"

    _hits=$(wt_hits "$_rows" "$_p")
    _stripped=""
    _prefix=""
    if [ -z "$_hits" ] && [ "${_p%%/*}" != "$_p" ]; then
      # The convention this tool enforces is `<repo>/<file>:<line>`, so a
      # correctly-formatted citation carries a leading <repo>/ that is NOT part
      # of any tree-relative path. Strip it and retry — but KEEP it: it is the
      # author's claim about which tree they meant, and checking that claim is
      # the entire point. The first draft discarded it and reported a fully
      # qualified citation as "ambiguous", which is the tool failing at its own
      # convention.
      _prefix=${_p%%/*}
      _stripped=${_p#*/}
      _hits=$(wt_hits "$_rows" "$_stripped")
      if [ -n "$_hits" ]; then
        _claimed=$(wt_prefix_match "$_hits" "$_prefix")
        if [ -n "$_claimed" ]; then
          _hits="$_claimed"
        else
          # The cited repo does not hold the path. THIS is the 2026-08-24 bug:
          # a session resolved client/src/design/tokens.css to a tree that never
          # contained it and nearly filed a false finding off that.
          echo "      🔴 MISATTRIBUTED — no working tree named '$_prefix' holds this path."
          echo "         It DOES exist here:"
          printf '%s\n' "$_hits" | sort -t"$(printf '\t')" -k2,2nr \
            | awk -F'\t' '{n=split($1,r,"/");
                           printf "            %s/%s\n               %s · %s%s · tree %s\n",r[n],$7,$1,$4,$5,$3}'
          echo "         Do not cite '$_prefix' for this line. Re-resolve, then cite."
          if [ "$_worst" -lt 5 ]; then _worst=5; fi
          echo ""
          continue
        fi
      fi
    fi

    _count=$(printf '%s' "$_hits" | grep -c . || true)
    [ -n "$_count" ] || _count=0

    if [ "$_count" -eq 0 ]; then
      echo "      ⊘ NOT FOUND in any of the $_n working tree(s) scanned."
      echo "        A zero here means the path does not exist as written — check the"
      echo "        spelling, or the file may be uncommitted in a tree you can't see."
      if [ "$_worst" -lt 3 ]; then _worst=3; fi
    elif [ "$_count" -eq 1 ]; then
      printf '%s\n' "$_hits" | awk -F'\t' '{n=split($1,r,"/");
                       printf "      ✅ %s/%s\n         %s · %s%s · tree %s\n",r[n],$7,$1,$4,$5,$3}'
      if [ -n "$_prefix" ]; then
        echo "         (the cited '$_prefix' prefix matched this tree — citation is sound)"
      fi
    else
      echo "      ⚠ AMBIGUOUS — $_count trees hold this path. Resolve it before you cite it."
      printf '%s\n' "$_hits" | sort -t"$(printf '\t')" -k2,2nr \
        | awk -F'\t' '{n=split($1,r,"/"); tag = (NR==1 ? "   ← NEWEST HEAD" : "")
                       printf "         %s/%s%s\n            %s · %s%s · tree %s\n",r[n],$7,tag,$1,$4,$5,$3}'
      echo "         NEWEST HEAD marks the most recently committed tree. It is NOT"
      echo "         evidence of which one the citation meant — read the context."
      if [ "$_worst" -lt 4 ]; then _worst=4; fi
    fi
    echo ""
  done
  return "$_worst"
}

# Hits whose identity OR repo name OR tree directory name matches $2,
# case-insensitively. `Open-Scaffold-Labs/OpenFirehouse-private` is checked out
# at ~/openfirehouse, so a citation may legitimately name the full org/repo, just
# the repo, or the folder — all three are accepted.
wt_prefix_match() {
  local _hits="$1" _prefix="$2"
  printf '%s\n' "$_hits" | awk -F'\t' -v p="$_prefix" '
    { n=split($3,a,"/"); dir=a[n]
      m=split($1,r,"/"); repo=r[m]
      if (tolower($1)==tolower(p) || tolower(repo)==tolower(p) || tolower(dir)==tolower(p)) print }'
}

# Rows whose tree contains $2. Emits the enumeration row with the matched
# relative path appended as field 7.
#
# ⚠ DO NOT parse these rows with `IFS=$'\t' read -r a b c d e f`. Tab is IFS
# WHITESPACE, so bash collapses consecutive tabs into ONE delimiter — a row whose
# migration field is empty (every tree without docs/migrations/, which includes
# the Hub and the-match) silently loses a field, $_abs lands on the branch name,
# and the row is dropped. That shipped in the first draft of this file and made
# the positive control report NOT FOUND for a path that demonstrably exists in
# two trees. The absolute path is the LAST field precisely so it can be taken
# with `${_row##*<tab>}` — exact, fork-free, and blind to empty fields.
wt_hits() {
  local _rows="$1" _path="$2" _row _abs _tab
  [ -n "$_path" ] || return 0
  _tab=$(printf '\t')
  printf '%s\n' "$_rows" | while IFS= read -r _row; do
    [ -n "$_row" ] || continue
    _abs=${_row##*"$_tab"}
    [ -n "$_abs" ] || continue
    if [ -e "$_abs/$_path" ]; then
      printf '%s\t%s\n' "$_row" "$_path"
    fi
  done
}

# ── main ───────────────────────────────────────────────────────────────────────
if [ "$#" -eq 0 ]; then
  wt_usage
  exit 1
fi

case "$1" in
  --help|-h)
    wt_usage
    exit 0
    ;;
  --list)
    wt_list
    exit $?
    ;;
  -*)
    echo "whichtree.sh: unknown option '$1'" >&2
    echo "Try: tools/whichtree.sh --help" >&2
    exit 1
    ;;
esac

wt_resolve "$@"
exit $?
