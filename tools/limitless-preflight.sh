#!/bin/bash
# Limitless Stack — Roll Call / Preflight
# Runs on Matt's Mac (keychains, auth, CLIs live here).
# Invoked at session start via Claude's Roll Call skill:
#   mcp__desktop-commander__start_process("bash tools/limitless-preflight.sh", shell="zsh")
#
# Exit codes:
#   0  READY — all green
#   1  WARN  — yellow findings (drift / stale / uncommitted); session may proceed with acknowledgement
#   2  BLOCK — red findings (auth failed, files missing); do NOT start work until fixed
#   3  INDETERMINATE — this machine has no working network, so most checks CANNOT
#      be evaluated. NOT a verdict about the stack. See network_probe() below.
#
# Self-improvement rule: if a drift mode is discovered during a session that
# this script didn't catch, add a new check here before closing the session.

set -u

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$VAULT" || { echo "ERROR: cannot cd to vault $VAULT"; exit 2; }

# ── Canonical LimitlessStack root ───────────────────────
# MUST be defaulted HERE, above every consumer. Under `set -u` a reference
# before this line aborts the ENTIRE preflight: the sibling-repo git check
# shipped 2026-08-23 (08a2275) read it 172 lines early and killed checks 4-7
# in any shell where the variable was not already exported — which is every
# shell on this Mac (not in .zshenv/.zshrc/.zprofile/.zlogin, not in
# `launchctl getenv`, not exported by nightly-selfheal.sh).
#
# GUESSING one address is not the same as FINDING the thing (Matt, 2026-08-24:
# "shouldnt it guide them where to look considering we already know what its
# looking for"). A bare `${VAR:-/Users/...}` still lands on a Mac path whenever
# nobody exports the variable — which is every shell on every other machine. So:
# search the places it actually lives, take the first REAL match (a directory
# that contains what we expect), and only then fall back — so the fallback is
# the last resort in a search, not the whole strategy.
find_repo() {
  # $1 = marker file that proves it is the right repo, $2.. = candidate paths.
  local _marker="$1"; shift
  local _c
  for _c in "$@"; do
    [ -n "$_c" ] && [ -e "$_c/$_marker" ] && { printf '%s' "$_c"; return 0; }
  done
  printf '%s' "$1"   # nothing matched: echo the first candidate so messages name a real place
}

LIMITLESS_STACK_HOME="$(find_repo "install.sh" \
  "${LIMITLESS_STACK_HOME:-}" \
  "$HOME/LimitlessStack" \
  "$(dirname "$VAULT")/LimitlessStack" \
  "$(dirname "$(dirname "$VAULT")")/LimitlessStack")"
[ -n "$LIMITLESS_STACK_HOME" ] || LIMITLESS_STACK_HOME="$HOME/LimitlessStack"

HUB_REPO="$(find_repo "CLAUDE.md" \
  "${HUB_REPO:-}" \
  "$HOME/limitless-stack-hub" \
  "$(dirname "$VAULT")/limitless-stack-hub" \
  "$(dirname "$(dirname "$VAULT")")/limitless-stack-hub")"
[ -n "$HUB_REPO" ] || HUB_REPO="$HOME/limitless-stack-hub"

# ── Completion assertion ────────────────────────────────
# A preflight that dies mid-run must NOT wear the exit code that means
# "proceed". `set -u` aborts with status 1, which this file's own header
# documents as WARN — so a DEAD gate is indistinguishable from a mildly
# drifted one, and nightly-selfheal.sh renders it as
# "READY* — 0 known-accepted residual (no action)" having evaluated nothing.
#
# Second occurrence of this class in this file: dd10778 (2026-05-18) hit
# ${WARNINGS[*]} inside $( ) — subshell-only, so it was labelled "cosmetic",
# patched at two literal call sites, and the class left open.
#
# The flag flips true at each LEGITIMATE terminal state. There are exactly
# three below this line (verified by an exhaustive grep of `exit <n>`):
# --help, network_abort's INDETERMINATE exit 3, and the final verdict chain.
# Anything else reaching EXIT is an abort.
#
# Do NOT add $LINENO to the banner: inside an EXIT trap it does not report the
# failing line (measured on bash 3.2.57 — said 12 where stderr said 10).
# $BASH_COMMAND DOES survive into the trap (measured), so it names the command.
# Fenced by tools/test-preflight-abort.sh — mutation-proven, with a negative
# control that fails if this trap is removed.
PREFLIGHT_COMPLETED=false
trap '_rc=$?
      if [ "$PREFLIGHT_COMPLETED" != true ]; then
        echo ""
        echo "═══════════════════════════════════════════════════════"
        echo "  ⨯ VERDICT: ABORTED — died before reaching a verdict (rc=$_rc)"
        echo "  Failing command: ${BASH_COMMAND:-<unknown>}"
        echo "  NOTHING WAS EVALUATED — this is NOT a verdict about the stack."
        echo "  Do not proceed on this run. The failing line is on stderr above."
        echo "═══════════════════════════════════════════════════════"
        exit 2
      fi' EXIT

# ── Project manifest ────────────────────────────────────
# If $VAULT/.limitless-project.py exists, read its CHECKS list to determine
# which preflight sections run. Lets each project (Hub, the-match, future
# greenfield apps) declare its own subset of the seven-tool stack.
# Backwards-compat: no manifest → all checks run (Hub-vault behavior).
LIMITLESS_PROJECT_ID="hub"  # default
LIMITLESS_HAS_MANIFEST=false
LIMITLESS_CHECKS=""
LIMITLESS_DESCRIPTION=""
LIMITLESS_PROJECT_ROUTES=""        # space-separated "label:filepath" pairs from manifest NOTEBOOKLM.routes
LIMITLESS_DEDUPE_NOTEBOOKS=""      # space-separated "shortid:label" pairs for dedupe sweep
LIMITLESS_REMINDER_FILES=""        # space-separated paths from manifest NOTEBOOKLM.reminder.files
LIMITLESS_DEFAULT_NB_ID=""         # full UUID
LIMITLESS_DEFAULT_NB_LABEL=""
LIMITLESS_REMINDER_NB_ID=""
LIMITLESS_OBSIDIAN_MIN_PAGES="10"  # default; manifest's OBSIDIAN.expected_min_pages overrides

if [ -f "$VAULT/.limitless-project.py" ]; then
  LIMITLESS_HAS_MANIFEST=true
  LIMITLESS_MANIFEST_RAW=$(python3.11 -c "
import importlib.util, sys
try:
    spec = importlib.util.spec_from_file_location('_m', '$VAULT/.limitless-project.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    print('PROJECT_ID=' + getattr(m, 'PROJECT_ID', 'unknown'))
    print('CHECKS=' + ' '.join(getattr(m, 'CHECKS', [])))
    print('DESCRIPTION=' + getattr(m, 'DESCRIPTION', ''))
    obs = getattr(m, 'OBSIDIAN', {}) or {}
    print('OBSIDIAN_MIN_PAGES=' + str(obs.get('expected_min_pages', 10)))
    nb = getattr(m, 'NOTEBOOKLM', {}) or {}
    routes = nb.get('routes', [])
    default = nb.get('default')
    reminder = nb.get('reminder', {}) or {}
    print('PROJECT_ROUTES=' + ' '.join(f'{r[2]}:{r[0]}' for r in routes))
    dedupe_items = []
    for r in routes:
        dedupe_items.append(f'{r[1].split(chr(45))[0]}:{r[2]}')
    if default:
        dedupe_items.append(f'{default[0].split(chr(45))[0]}:{default[1]}')
    if reminder.get('notebook_id'):
        rid = reminder['notebook_id'].split('-')[0]
        dedupe_items.append(f'{rid}:reminder')
    print('DEDUPE_NOTEBOOKS=' + ' '.join(dedupe_items))
    print('REMINDER_FILES=' + ' '.join(reminder.get('files', [])))
    if default:
        print('DEFAULT_NB_ID=' + default[0])
        print('DEFAULT_NB_LABEL=' + default[1])
    if reminder.get('notebook_id'):
        print('REMINDER_NB_ID=' + reminder['notebook_id'])
except Exception as e:
    print('ERROR=' + str(e), file=sys.stderr)
" 2>&1)
  LIMITLESS_PROJECT_ID=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^PROJECT_ID=' | cut -d= -f2-)
  LIMITLESS_CHECKS=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^CHECKS=' | cut -d= -f2-)
  LIMITLESS_DESCRIPTION=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^DESCRIPTION=' | cut -d= -f2-)
  LIMITLESS_OBSIDIAN_MIN_PAGES=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^OBSIDIAN_MIN_PAGES=' | cut -d= -f2-)
  LIMITLESS_PROJECT_ROUTES=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^PROJECT_ROUTES=' | cut -d= -f2-)
  LIMITLESS_DEDUPE_NOTEBOOKS=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^DEDUPE_NOTEBOOKS=' | cut -d= -f2-)
  LIMITLESS_REMINDER_FILES=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^REMINDER_FILES=' | cut -d= -f2-)
  LIMITLESS_DEFAULT_NB_ID=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^DEFAULT_NB_ID=' | cut -d= -f2-)
  LIMITLESS_DEFAULT_NB_LABEL=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^DEFAULT_NB_LABEL=' | cut -d= -f2-)
  LIMITLESS_REMINDER_NB_ID=$(echo "$LIMITLESS_MANIFEST_RAW" | grep '^REMINDER_NB_ID=' | cut -d= -f2-)
fi

# Returns 0 if a named check is enabled (in manifest CHECKS list, or no manifest = all enabled).
# Use as: `if check_enabled <name>; then ... fi`
check_enabled() {
  local name="$1"
  # No manifest at all → all checks enabled (Hub-vault backwards-compat).
  # Manifest with empty CHECKS list → no optional checks enabled (explicit
  # opt-out); the empty-string LIMITLESS_CHECKS no longer collides with
  # the no-manifest case thanks to LIMITLESS_HAS_MANIFEST.
  [ "$LIMITLESS_HAS_MANIFEST" = "false" ] && return 0
  echo " $LIMITLESS_CHECKS " | grep -q " $name "
}

# Counters + finding lists
GREEN=0
YELLOW=0
RED=0
ACCEPTED=0
WARNINGS=()
BLOCKERS=()
ACCEPTED_NOTES=()

# ── CLI args ────────────────────────────────────────────
# --json-out         → writes ~/.cache/limitless-stack/health.json with payload
# --json-out=PATH    → writes payload to an explicit path
# --findings-out=PATH→ writes a machine-readable findings JSON at verdict time:
#                      {verdict,green,yellow,red,warnings[],blockers[],generated_at}.
#                      This is the STABLE channel for programmatic consumers
#                      (the Loop 5 nightly) so they never have to scrape the
#                      human-readable "  - msg  →  fix" lines — a cosmetic output
#                      edit would otherwise silently break every consumer (a SPOF
#                      both the Loop 5 and Loop 6 audits flagged, 2026-07-23).
#                      Human output is UNCHANGED whether or not this is passed.
JSON_OUT=""
FINDINGS_OUT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --json-out)       JSON_OUT="${HOME}/.cache/limitless-stack/health.json" ;;
    --json-out=*)     JSON_OUT="${1#*=}" ;;
    --findings-out=*) FINDINGS_OUT="${1#*=}" ;;
    -h|--help)
      echo "usage: limitless-preflight.sh [--json-out[=PATH]] [--findings-out=PATH]"
      echo "  --findings-out=PATH  write machine-readable findings JSON (for the nightly)."
      echo "  POST to the Hub happens automatically if Keychain has"
      echo "  lsh-stack-health-token (shared secret)."
      PREFLIGHT_COMPLETED=true          # legitimate terminal state (see trap)
      exit 0 ;;
    *) echo "unknown arg: $1" >&2 ;;
  esac
  shift
done

# Shared timestamp — used by multiple freshness checks below.
NOW_TS=$(date +%s)

# ── Per-tool state accumulators (for the Hub's /today Stack Status card) ────
# Each [n/7] block calls begin_tool at its top; ok/warn/bad update the current
# tool's metric + downgrade counters; finalize_tool at the very end emits the
# last tool and we POST the full payload to the Hub.
CURRENT_TOOL_ID=""
CURRENT_TOOL_LABEL=""
CURRENT_TOOL_ROLE=""
CURRENT_TOOL_METRIC=""
CURRENT_TOOL_YELLOW=0
CURRENT_TOOL_RED=0
TOOL_STATES=()

begin_tool() {
  [ -n "$CURRENT_TOOL_ID" ] && finalize_tool
  CURRENT_TOOL_ID="$1"
  CURRENT_TOOL_LABEL="$2"
  CURRENT_TOOL_ROLE="$3"
  CURRENT_TOOL_METRIC=""
  CURRENT_TOOL_YELLOW=0
  CURRENT_TOOL_RED=0
}

finalize_tool() {
  [ -z "$CURRENT_TOOL_ID" ] && return 0
  local status="ok"
  if   [ "$CURRENT_TOOL_RED"    -gt 0 ]; then status="danger"
  elif [ "$CURRENT_TOOL_YELLOW" -gt 0 ]; then status="warn"
  fi
  local metric="${CURRENT_TOOL_METRIC:-—}"
  local blob
  blob=$(python3 -c 'import sys,json;print(json.dumps({"id":sys.argv[1],"label":sys.argv[2],"role":sys.argv[3],"status":sys.argv[4],"health":sys.argv[5]}))'     "$CURRENT_TOOL_ID" "$CURRENT_TOOL_LABEL" "$CURRENT_TOOL_ROLE" "$status" "$metric")
  TOOL_STATES+=("$blob")
  CURRENT_TOOL_ID=""
}

# Console helpers (extended to update the per-tool state used by begin_tool).
# The first call of any kind sets the tool's health string; ok prefers its own
# message (useful metric) over warn/bad (error strings) so a section that
# started with an ok check still shows the metric.
ok()    {
  echo "  ✓ $1"
  GREEN=$((GREEN+1))
  if [ -z "$CURRENT_TOOL_METRIC" ] || [ "${CURRENT_TOOL_METRIC:0:1}" = "⚠" ] || [ "${CURRENT_TOOL_METRIC:0:1}" = "✗" ]; then
    CURRENT_TOOL_METRIC="$1"
  fi
}
warn()  {
  echo "  ⚠ $1"
  YELLOW=$((YELLOW+1))
  CURRENT_TOOL_YELLOW=$((CURRENT_TOOL_YELLOW+1))
  WARNINGS+=("$1  →  $2")
  [ -z "$CURRENT_TOOL_METRIC" ] && CURRENT_TOOL_METRIC="⚠ $1"
}
bad()   {
  echo "  ✗ $1"
  RED=$((RED+1))
  CURRENT_TOOL_RED=$((CURRENT_TOOL_RED+1))
  BLOCKERS+=("$1  →  $2")
  [ -z "$CURRENT_TOOL_METRIC" ] && CURRENT_TOOL_METRIC="✗ $1"
}
skip()  { echo "  ⊘ $1"; }
# accepted() — a KNOWN state that is real, visible, and NOT drift: nobody in this
# session can clear it, and CLAUDE.md already documents it. It PRINTS (so the state
# never goes invisible) but does NOT increment YELLOW and does NOT enter WARNINGS,
# so it can never pin the verdict.
#
# ⚠ USE THIS SPARINGLY, AND ONLY FOR THE ROLL-CALL AUDIENCE. A false green is
# believed; a false red is eventually investigated. The bar is: an account-level or
# external blocker that a session is FORBIDDEN or unable to act on. It is NOT for
# "we keep seeing this one." In particular do NOT accept() "uncommitted files in
# vault" or "anti-pattern review due" — the nightly excludes those because a
# CORRECTOR cannot act on them, but a HUMAN at Roll Call can and should.
# That difference in audience is why this list is deliberately shorter than
# nightly-selfheal.sh's ACCEPTED_RE, and why the two are not merged.
# Added 2026-08-20.
accepted() {
  echo "  ℹ $1"
  ACCEPTED=$((ACCEPTED+1))
  ACCEPTED_NOTES+=("$1  →  $2")
}

# ── Network reachability gate (added 2026-07-27) ────────
#
# WHY THIS EXISTS
# On 2026-07-27 the nightly self-heal returned BLOCK with 2 red and 12 yellow.
# It looked like fourteen problems. It was one: the laptop lost DNS mid-run.
# Pass 1 at 07:52 was green=34 yellow=11 red=0; passes 2 and 3 at 08:28/08:30
# were red=2 — and every finding that appeared in between was a network-
# dependent check reporting its own inability to reach the internet:
# NameResolutionError on api.pinecone.io, `notebooklm list` failing, notebook
# coverage exit=2, notebook capacity exit=2, hermes unhealthy, paperclip HTTP
# 000. Three hours later the same checks were all green.
#
# The mechanism that turned a blip into needs_human is worth naming: the Loop 5
# accepted-findings allowlist matches the Pinecone QUOTA text specifically, so a
# DNS-class failure of that same probe did not match and escalated instead of
# being absorbed. Widening the allowlist would be the wrong fix — it would
# swallow a real Pinecone outage too.
#
# THE PRINCIPLE: a verdict computed with no network is not a verdict. Report
# that we could not evaluate, rather than reporting a stack-wide failure that
# does not exist. A checker that cries wolf trains the next reader to ignore it,
# which is precisely what a preflight cannot afford.
#
# The probe deliberately separates two questions so it never mislabels a real
# outage as a network problem:
#   1. Is there IP connectivity at all?  → HTTPS to a literal IP (no DNS).
#   2. Does DNS resolve?                 → getaddrinfo on stable public hosts.
# BOTH must fail in their own way for us to declare the network down. If DNS
# resolves and IP connectivity works, then a single service being unreachable is
# a REAL finding and is reported normally — that path is unchanged.
#
# Probes are chosen to be independent of our own stack: none of them is Pinecone,
# NotebookLM, Fly, or GitHub, so their health says nothing about ours.
NET_STATE="unknown"
NET_DETAIL=""

network_probe() {
  local ip_ok=false dns_ok=false detail=""

  # 1. IP connectivity, no DNS involved. Two independent anycast resolvers.
  for ip in 1.1.1.1 8.8.8.8; do
    if curl -sS --max-time 6 -o /dev/null "https://$ip" 2>/dev/null; then ip_ok=true; break; fi
  done

  # 2. DNS resolution of stable third-party hosts. Any one success means DNS works.
  if python3.11 - <<'PY' >/dev/null 2>&1
import socket, sys
socket.setdefaulttimeout(6)
for host in ("one.one.one.one", "dns.google", "example.com"):
    try:
        socket.getaddrinfo(host, 443)
        sys.exit(0)
    except Exception:
        continue
sys.exit(1)
PY
  then dns_ok=true; fi

  if   $ip_ok && $dns_ok; then NET_STATE="up"
  elif $ip_ok;            then NET_STATE="dns-down"; detail="IP connectivity works but DNS does not resolve — the 2026-07-27 mode"
  else                         NET_STATE="offline";  detail="no IP connectivity and no DNS — machine is offline or asleep"
  fi
  NET_DETAIL="$detail"
  [ "$NET_STATE" = "up" ]
}

# Abort cleanly with exit 3, writing the machine-readable channel so the nightly
# gets a structured "indeterminate" rather than having to scrape for it.
network_abort() {
  local phase="$1"
  echo ""
  echo "───────────────────────────────────────────────────────"
  echo "  ⊘ VERDICT: INDETERMINATE — no working network ($NET_STATE, detected $phase)"
  echo ""
  echo "  $NET_DETAIL"
  echo ""
  echo "  This is NOT a finding about the Limitless Stack. Most checks reach the"
  echo "  network, so running them now would manufacture failures that say only"
  echo "  that this machine is offline. Nothing has been evaluated and no state"
  echo "  has been overwritten."
  echo ""
  echo "  Rerun when connectivity is back. If it is back and this still fires,"
  echo "  THAT is a real finding — investigate the probe, not the stack."
  echo "───────────────────────────────────────────────────────"
  if [ -n "$FINDINGS_OUT" ]; then
    mkdir -p "$(dirname "$FINDINGS_OUT")" 2>/dev/null
    printf '{"verdict":"indeterminate","reason":"network","net_state":"%s","phase":"%s","detail":"%s","green":0,"yellow":0,"red":0,"warnings":[],"blockers":[],"generated_at":"%s"}\n' \
      "$NET_STATE" "$phase" "$NET_DETAIL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$FINDINGS_OUT"
  fi
  # Legitimate terminal state: INDETERMINATE is a documented contract (rc=3,
  # added 2026-07-27) and must NEVER be converted into a BLOCK by the trap —
  # that would resurrect the 2026-07-27 incident where a mid-run DNS drop
  # produced red=2/yellow=12 that looked like fourteen problems and was one.
  PREFLIGHT_COMPLETED=true
  exit 3
}

banner() {
  echo "═══════════════════════════════════════════════════════"
  echo "  LIMITLESS STACK — ROLL CALL"
  echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "═══════════════════════════════════════════════════════"
}

banner
echo ""

# Gate BEFORE any check runs. If the machine is offline, nothing below can be
# evaluated and pretending otherwise produces a stack-wide false alarm.
if ! network_probe; then network_abort "at start"; fi

# ── [1/7] Claude ────────────────────────────────────────
echo "[1/7] Claude (reasoning engine)"
begin_tool "claude" "Claude" "Reasoning"
ok "present (you are running this script)"
echo ""

# ── [2/7] CLAUDE.md ─────────────────────────────────────
echo "[2/7] CLAUDE.md (identity + rules)"
begin_tool "claudemd" "CLAUDE.md" "Identity"
if [ -r "$VAULT/CLAUDE.md" ] && [ -s "$VAULT/CLAUDE.md" ]; then
  LINES=$(wc -l <"$VAULT/CLAUDE.md" | tr -d ' ')
  ok "readable ($LINES lines)"
else
  bad "CLAUDE.md missing or empty" "restore CLAUDE.md from git (git checkout CLAUDE.md)"
fi
echo ""

# ── [3/7] Obsidian wiki ─────────────────────────────────
# MANDATORY: every Limitless Stack project must have a wiki/. Cannot be
# disabled via the manifest's CHECKS list. New projects without a wiki
# should run `limitless-stack-init` to scaffold one.
echo "[3/7] Obsidian wiki (knowledge base)"
begin_tool "obsidian" "Obsidian" "Knowledge"
if [ -r "$VAULT/wiki/index.md" ]; then
  PAGES=$(find "$VAULT/wiki" -name '*.md' | wc -l | tr -d ' ')
  if [ "$PAGES" -gt "$LIMITLESS_OBSIDIAN_MIN_PAGES" ]; then
    ok "wiki/index.md readable · $PAGES pages total"
  else
    warn "only $PAGES wiki pages found" "expected >$LIMITLESS_OBSIDIAN_MIN_PAGES (manifest OBSIDIAN.expected_min_pages); verify vault is intact or seed wiki content"
  fi
else
  bad "wiki/index.md missing or unreadable" "verify vault path + Obsidian sync"
fi

# Git status — uncommitted work
if [ -d "$VAULT/.git" ]; then
  UNCOMMITTED=$(git -C "$VAULT" status --porcelain | wc -l | tr -d ' ')
  if [ "$UNCOMMITTED" -eq 0 ]; then
    ok "git clean (no uncommitted changes)"
  else
    warn "$UNCOMMITTED uncommitted files in vault" "git -C \"$VAULT\" status --short · ask Matt before committing"
  fi

  # Unpushed commits
  UNPUSHED=$(git -C "$VAULT" log origin/main..HEAD --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [ "$UNPUSHED" -gt 0 ]; then
    warn "$UNPUSHED commits ahead of origin/main" "git -C \"$VAULT\" push origin main"
  fi
else
  warn "vault is not a git repo" "check vault location; end-of-session commit/push won't work"
fi

# Sibling repos' git state. ADDED 2026-08-23 after a clause-by-clause audit of
# CLAUDE.md step 0.4 ("leave nothing dirty in EVERY repo touched") found the
# preflight checked the VAULT only — 0 checks for the Hub or the canonical
# LimitlessStack. So "clean" was mechanically enforced for one of three repos
# and prose-only for the other two, which is exactly how a local commit sits
# unpushed overnight without anything noticing.
# Read-only: reports, never commits. Missing repo = skip, not a warning.
for _sib in "$HUB_REPO:Hub" \
            "$LIMITLESS_STACK_HOME:LimitlessStack"; do
  _sib_path="${_sib%%:*}"; _sib_name="${_sib##*:}"
  if [ -d "$_sib_path/.git" ]; then
    # `grep -c` PRINTS 0 and EXITS 1 when it matches nothing, so the original
    # `|| echo 0` appended a SECOND line: _dirty became "0\n0", every [ -eq ]
    # below died with "integer expression expected", and a CLEAN sibling repo
    # therefore printed neither ok nor warn — the check was fail-silent in
    # exactly the case it was written to confirm. `|| true` keeps grep's own 0.
    _dirty=$(git -C "$_sib_path" status --porcelain 2>/dev/null | grep -vc '^??' || true)
    _ahead=$(git -C "$_sib_path" log origin/main..HEAD --oneline 2>/dev/null | wc -l | tr -d ' ')
    if [ "${_dirty:-0}" -eq 0 ] && [ "${_ahead:-0}" -eq 0 ]; then
      ok "$_sib_name repo clean and pushed"
    else
      [ "${_dirty:-0}" -gt 0 ] && warn "$_sib_name: $_dirty tracked file(s) modified" \
        "git -C \"$_sib_path\" status --short · ask Matt before committing (untracked files are not counted)"
      [ "${_ahead:-0}" -gt 0 ] && warn "$_sib_name: $_ahead commit(s) ahead of origin/main" \
        "git -C \"$_sib_path\" push origin main"
    fi
  else
    skip "$_sib_name git state: no repo at $_sib_path"
  fi
done

# ── Wiki content freshness (semantic) ───────────────────
# These three checks look at CONTENT of wiki files (not just presence /
# timestamps), specifically for drift modes that mechanical checks miss:
#   1. Pages exist in wiki/ but aren't listed in wiki/index.md (catalog drift)
#   2. Pages contain literal template placeholders (overview.md never filled in)
#   3. TODO files have explicit deadlines that have passed (overdue items)
# Added 2026-05-07 after a session discovered HIGH-PRIORITY-TODO.md sat
# 3 days overdue + the-match CLAUDE.md feature table was 1 week stale
# without any preflight check noticing. See claude-anti-patterns.md
# entry "Mechanical checks without semantic checks". Attributed to the
# obsidian tool (no new begin_tool call) since these are wiki-health.
if [ -r "$VAULT/wiki/index.md" ]; then
  # Check 1: index completeness — every wiki/*.md (except index.md) should
  # appear by basename or relative-path in wiki/index.md.
  MISSING_FROM_INDEX=()
  while IFS= read -r page; do
    [ "$page" = "$VAULT/wiki/index.md" ] && continue
    REL="${page#$VAULT/wiki/}"
    BASE="${REL%.md}"
    # grep -F for literal string match; check both basename + relative path
    if ! grep -qF "$BASE" "$VAULT/wiki/index.md" 2>/dev/null; then
      MISSING_FROM_INDEX+=("$REL")
    fi
  done < <(find "$VAULT/wiki" -name '*.md' -type f 2>/dev/null)
  if [ ${#MISSING_FROM_INDEX[@]} -eq 0 ]; then
    ok "index.md catalog complete (every wiki/*.md is listed)"
  else
    warn "${#MISSING_FROM_INDEX[@]} wiki page(s) not listed in wiki/index.md: ${MISSING_FROM_INDEX[*]}" "edit wiki/index.md to add them, or document why they're excluded"   # unbound-ok: else-branch of ${#MISSING_FROM_INDEX[@]} -eq 0
  fi

  # Check 2: template-placeholder detection — frontmatter dates literally set
  # to YYYY-MM-DD mean the page was scaffolded by limitless-stack-init and
  # never filled in.
  PLACEHOLDERS=()
  while IFS= read -r page; do
    if head -10 "$page" 2>/dev/null | grep -qE "^(created|updated): YYYY-MM-DD"; then
      PLACEHOLDERS+=("$(basename "$page")")
    fi
  done < <(find "$VAULT/wiki" -name '*.md' -type f 2>/dev/null)
  if [ ${#PLACEHOLDERS[@]} -eq 0 ]; then
    ok "no template-placeholder dates left in wiki"
  else
    warn "${#PLACEHOLDERS[@]} wiki page(s) still have YYYY-MM-DD placeholder frontmatter: ${PLACEHOLDERS[*]}" "fill in the page content + real dates, or delete the page"   # unbound-ok: else-branch of ${#PLACEHOLDERS[@]} -eq 0
  fi

  # Check 3: overdue TODO detection — two passes:
  #   3a. wiki/*TODO*.md with `priority: critical` frontmatter older than 3 days
  #   3b. any scanned file with explicit "DO AFTER YYYY-MM-DD" past today
  # Uses the global NOW_TS set at the top of the script.
  #
  # WHAT GETS SCANNED (widened 2026-08-07): the legacy wiki/*TODO*.md glob PLUS
  # the task files CLAUDE.md step 0 says now hold in-flight and overdue work.
  # Keyed on where the items actually live, not on a filename convention — a
  # naming convention is a hand-kept list wearing a different hat (#65 addendum).
  deadline_scan_files() {
    find "$VAULT/wiki" -iname '*TODO*.md' -type f 2>/dev/null
    [ -f "$VAULT/wiki/team-tasks.md" ] && echo "$VAULT/wiki/team-tasks.md"
    find "$VAULT/wiki/my-tasks" -name '*.md' -type f 2>/dev/null
    return 0
  }
  OVERDUE=()
  while IFS= read -r todofile; do
    NAME=$(basename "$todofile")
    # 3a: critical-priority age check
    if head -10 "$todofile" 2>/dev/null | grep -qE "^priority:[[:space:]]*critical"; then
      CREATED=$(head -10 "$todofile" 2>/dev/null | grep -E "^created:" | head -1 | sed -E 's/^created:[[:space:]]*//' | tr -d ' ')
      if [ -n "$CREATED" ] && echo "$CREATED" | grep -qE "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"; then
        CREATED_TS=$(date -j -f "%Y-%m-%d" "$CREATED" +%s 2>/dev/null || echo 0)
        if [ "$CREATED_TS" -gt 0 ]; then
          AGE_DAYS=$(( (NOW_TS - CREATED_TS) / 86400 ))
          if [ "$AGE_DAYS" -gt 3 ]; then
            OVERDUE+=("$NAME (priority:critical, ${AGE_DAYS}d old since $CREATED)")
            continue  # one finding per file
          fi
        fi
      fi
    fi
    # 3b: explicit "DO AFTER YYYY-MM-DD" past today
    DEADLINE=$(grep -oE 'DO AFTER [0-9]{4}-[0-9]{2}-[0-9]{2}|by [0-9]{4}-[0-9]{2}-[0-9]{2}|before [0-9]{4}-[0-9]{2}-[0-9]{2}' "$todofile" 2>/dev/null | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
    if [ -n "$DEADLINE" ]; then
      DEADLINE_TS=$(date -j -f "%Y-%m-%d" "$DEADLINE" +%s 2>/dev/null || echo 0)
      if [ "$DEADLINE_TS" -gt 0 ] && [ "$DEADLINE_TS" -lt "$NOW_TS" ]; then
        DAYS_OVERDUE=$(( (NOW_TS - DEADLINE_TS) / 86400 ))
        OVERDUE+=("$NAME (${DAYS_OVERDUE}d past explicit deadline $DEADLINE)")
      fi
    fi
  done < <(deadline_scan_files)
  # COVERAGE FLOOR — the fix for a check that was measuring nothing.
  # Until 2026-08-07 this scanned `find "$VAULT/wiki" -iname '*TODO*.md'`, which
  # has matched ZERO files since both TODO files were deleted (CLAUDE.md records
  # the deletion, 2026-08-05). So it printed "✓ no overdue TODO items detected"
  # over an empty set, every session, forever — anti-pattern #54 (a probe run
  # where the condition cannot exist) living inside the mechanism built to
  # satisfy #13b, i.e. #67 in the wild. A zero-finding result and a
  # zero-file-scanned result were indistinguishable, which is exactly what #65's
  # "assert COVERAGE before cleanliness" forbids. Now the count is asserted and
  # reported, so a green means something.
  SCANNED=$(deadline_scan_files | grep -c . || true)
  if [ "$SCANNED" -eq 0 ]; then
    warn "overdue-deadline scan found NO files to scan — the check is vacuous" \
         "expected wiki/team-tasks.md, wiki/my-tasks/*.md or a wiki/*TODO*.md; verify the globs in tools/limitless-preflight.sh"
  elif [ ${#OVERDUE[@]} -eq 0 ]; then
    ok "no overdue items in $SCANNED task/TODO file(s)"
  else
    warn "${#OVERDUE[@]} overdue item(s) across $SCANNED task file(s): ${OVERDUE[*]}" "address the items, then update the task file"   # unbound-ok: else-branch of ${#OVERDUE[@]} -eq 0
  fi
fi
echo ""

# ── Limitless Stack canonical sync ──────────────────────
# Hub vault's tools/ and ~/.claude/skills/ MUST match the LimitlessStack
# canonical at $LIMITLESS_STACK_HOME (default /Users/matthewlavin/LimitlessStack).
# Closes the failure mode where fixes accumulate in one place but never make it
# back to the other — observed 2026-04-29 when 174 lines of cmd_replace/
# routing/coverage fixes lived in the Hub vault for a session before the gap
# was caught. The contract is: any future drift here fails the next session's
# Roll Call, with a one-line cp command in the warning so it can't go unfixed.
# Emit a DIRECTION-AWARE drift warning. The remediation must never propose
# overwriting the newer copy with the older one. Added 2026-08-03: the skills
# check hardcoded canonical->installed, and following it literally would have
# rolled the notebooklm skill back from v0.7.3 to the April v0.3.4 — silently
# reinstating documented false-positive traps (e.g. bare `auth check --json`).
# Direction: an embedded `notebooklm-py vX.Y.Z` marker WINS when both sides
# carry one and they differ — mtime lies (a touch, a git checkout, or an
# install.sh run bumps it without changing content). Falls back to mtime when
# there is no version signal, or when both sides report the same version.
canonical_drift_warn() {
  local label="$1" canon="$2" local_f="$3"
  local canon_mt local_mt canon_v local_v vnote="" local_newer=false
  canon_mt=$(stat -f %m "$canon" 2>/dev/null || echo 0)
  local_mt=$(stat -f %m "$local_f" 2>/dev/null || echo 0)
  canon_v=$(grep -m1 -oE 'notebooklm-py v[0-9]+\.[0-9]+\.[0-9]+' "$canon" 2>/dev/null | sed 's/.*v//')
  local_v=$(grep -m1 -oE 'notebooklm-py v[0-9]+\.[0-9]+\.[0-9]+' "$local_f" 2>/dev/null | sed 's/.*v//')
  [ -n "$canon_v$local_v" ] && vnote=" [canonical v${canon_v:-?} · local v${local_v:-?}]"

  if [ -n "$canon_v" ] && [ -n "$local_v" ] && [ "$canon_v" != "$local_v" ]; then
    # Version marker is authoritative. `sort -V` puts the higher version last.
    [ "$(printf '%s\n%s\n' "$canon_v" "$local_v" | sort -V | tail -1)" = "$local_v" ] && local_newer=true
    vnote="$vnote (by version marker)"
  else
    [ "$local_mt" -gt "$canon_mt" ] && local_newer=true
    [ -n "$vnote" ] && vnote="$vnote (by mtime)"
  fi

  if $local_newer; then
    warn "$label drifted — LOCAL is newer, PROMOTE it to canonical$vnote" \
         "cp \"$local_f\" \"$canon\"  — do NOT copy the other way, it would downgrade"
  else
    warn "$label drifted — CANONICAL is newer$vnote" \
         "cp \"$canon\" \"$local_f\""
  fi
}

echo "[meta] Limitless Stack canonical sync"
# ($LIMITLESS_STACK_HOME is defaulted once, at the top of this file — one
#  evaluator, no second default to drift out of step.)
if [ -d "$LIMITLESS_STACK_HOME/tools" ]; then
  tools_clean=true
  # Dynamic: iterate over every file in canonical tools/. Adding a new tool
  # to LimitlessStack/tools/ automatically gets sync-checked next session
  # without code changes here. Files missing from this vault are skipped
  # (project-specific tooling stays project-specific until explicitly synced).
  for canon in "$LIMITLESS_STACK_HOME/tools/"*; do
    [ -f "$canon" ] || continue
    fname=$(basename "$canon")
    local_f="$VAULT/tools/$fname"
    [ -f "$local_f" ] || continue
    if ! diff -q "$canon" "$local_f" >/dev/null 2>&1; then
      tools_clean=false
      canonical_drift_warn "tools/$fname" "$canon" "$local_f"
    fi
  done
  if $tools_clean; then
    ok "tools/ in sync with LimitlessStack canonical ($LIMITLESS_STACK_HOME)"
  fi

  # HOOKS — added 2026-08-07, and the gap it closes is the point.
  # This sync check exists to stop fixes accumulating in one vault. It covered
  # tools/ and skills/ and NOTHING ELSE — so the five .claude/hooks/ scripts,
  # including both PreToolUse gates, were outside the one mechanism built to
  # propagate safeguards. The canonical had no hooks/ at all, install.sh never
  # deployed any, and this check reported "in sync" the whole time. A project
  # scaffolded from the canonical inherited ZERO PreToolUse gates while the Hub
  # vault had been blocking those same commands for months. The propagator could
  # not see this class of safeguard — anti-pattern #67, in the propagator.
  # Enumerated dynamically like tools/, so a sixth hook is covered automatically.
  if [ -d "$LIMITLESS_STACK_HOME/hooks" ]; then
    hooks_clean=true
    hooks_seen=0
    for canon in "$LIMITLESS_STACK_HOME/hooks/"*; do
      [ -f "$canon" ] || continue
      fname=$(basename "$canon")
      [ "$fname" = "settings.hooks.json" ] && continue   # template, spliced by install.sh
      local_f="$VAULT/.claude/hooks/$fname"
      [ -f "$local_f" ] || continue
      hooks_seen=$((hooks_seen + 1))
      if ! diff -q "$canon" "$local_f" >/dev/null 2>&1; then
        hooks_clean=false
        canonical_drift_warn ".claude/hooks/$fname" "$canon" "$local_f"
      fi
    done
    # Coverage floor — a zero-file sweep and a zero-drift sweep are otherwise
    # indistinguishable (#65: assert coverage before cleanliness).
    if [ "$hooks_seen" -eq 0 ]; then
      warn "hooks sync check compared NOTHING — 0 files matched" \
           "expected $VAULT/.claude/hooks/*.sh to mirror $LIMITLESS_STACK_HOME/hooks/"
    elif $hooks_clean; then
      ok ".claude/hooks/ in sync with canonical ($hooks_seen files)"
    fi
  else
    warn "LimitlessStack canonical has no hooks/ directory" \
         "a project installed from it inherits NO PreToolUse gates; populate $LIMITLESS_STACK_HOME/hooks/"
  fi

  skills_clean=true
  for s in limitless-stack roll-call notebooklm four-tool-lookup verify-before-claim karpathy-guidelines; do
    canon="$LIMITLESS_STACK_HOME/skills/$s/SKILL.md"
    installed="$HOME/.claude/skills/$s/SKILL.md"
    [ -f "$canon" ] || continue
    if [ ! -f "$installed" ]; then
      skills_clean=false
      warn "skill '$s' missing from ~/.claude/skills/" \
           "mkdir -p ~/.claude/skills/$s && cp $LIMITLESS_STACK_HOME/skills/$s/SKILL.md ~/.claude/skills/$s/SKILL.md"
      continue
    fi
    if ! diff -q "$canon" "$installed" >/dev/null 2>&1; then
      skills_clean=false
      canonical_drift_warn "skill '$s'" "$canon" "$installed"
    fi
  done
  if $skills_clean; then
    ok "skills in sync with LimitlessStack canonical"
  fi

  # ── The agent skill stores this loop CANNOT see (added 2026-08-20) ────
  # The loop above compares exactly two places: the LimitlessStack canonical and
  # ~/.claude/skills. On 2026-08-20 the notebooklm skill turned out to live in
  # FOUR, and the two extra ones had been stale since April — a Cowork ACCOUNT
  # copy at v0.3.4 (still documenting `download audio ./output.mp3`, which has
  # been .m4a for five minor versions) plus ~/.agents/skills. The sync contract
  # could not see either, so nothing ever said so. This is the hooks/ lesson
  # again: a mechanism that propagates safeguards could not see a whole class of
  # safeguard, and its blind spot was invisible precisely because it was blind.
  #
  # Two halves, because the two stores fail differently:
  #   (a) the CLI already reports its own installed targets — ask IT, don't
  #       reimplement its knowledge (`notebooklm skill status`).
  #   (b) the Cowork account copy is surfaced only as a READ-ONLY cache under a
  #       path containing a per-workspace id and an opaque hash, so it must be
  #       GLOBBED, never hardcoded — a literal path would rot silently, which is
  #       the same failure as the overdue-TODO scan that globbed zero files for
  #       two days and printed a checkmark over an empty set.
  if command -v notebooklm >/dev/null 2>&1; then
    NB_STATUS=$(notebooklm skill status 2>/dev/null)
    NB_CLI_V=$(printf '%s' "$NB_STATUS" | sed -n 's/.*CLI version: *\([0-9.]*\).*/\1/p' | head -1)
    NB_STALE=$(printf '%s' "$NB_STATUS" | sed -n 's/.*Skill version: *\([0-9.]*\).*/\1/p' \
               | grep -v "^${NB_CLI_V}$" | sort -u | paste -sd, -)
    if [ -n "$NB_CLI_V" ] && [ -n "$NB_STALE" ]; then
      warn "notebooklm skill stale in a CLI-managed store (cli $NB_CLI_V, found $NB_STALE)" \
           "notebooklm skill install   # updates every target the CLI manages"
    elif [ -n "$NB_CLI_V" ]; then
      ok "notebooklm skill current in all CLI-managed stores (v$NB_CLI_V)"
    fi

  fi

  # ── (b) EVERY skill, across EVERY Cowork ACCOUNT (rewritten 2026-08-20 PM) ──
  # This started as a notebooklm-only version-marker check. That was too narrow
  # twice over, and both were found the same evening:
  #
  #   1. Cowork stores are PER ACCOUNT. `local-agent-mode-sessions/<accountUuid>/
  #      <orgUuid>/` — confirmed by config.json's `lastKnownAccountUuid`, and
  #      proved by the skill SETS differing between the two (one account had six
  #      skills the other did not). Uploading a skill updates ONLY the account
  #      you were signed into. A second account does NOT self-heal by opening;
  #      it rebuilds its cache from its OWN stale store.
  #   2. Keying on a version marker only works for a vendor skill that has one.
  #      Matt's own skills carry no version, and TWO of them were stale in the
  #      account he does OpenScaffold work in — roll-call (April, missing the
  #      deferred-blocker protocol) and audit-before-claim (missing the
  #      "recommendations are claims too" section). Both had been invoked that
  #      session. Comparing by sha catches what a marker cannot.
  #
  # Skills absent from Cowork are NOT reported: several (limitless-stack,
  # karpathy-guidelines, of-module-hardening, impeccable) are in neither account
  # and are Claude Code-only by design. Absence is a choice; staleness is a bug.
  cw_seen=0; cw_stale=""
  for cw_skill in /var/folders/*/*/T/claude-hostloop-plugins/*/*/skills/*/SKILL.md; do
    [ -f "$cw_skill" ] || continue
    cw_seen=$((cw_seen+1))
    s_name=$(basename "$(dirname "$cw_skill")")
    s_ref="$HOME/.claude/skills/$s_name/SKILL.md"
    [ -f "$s_ref" ] || continue          # not one of ours to judge
    diff -q "$s_ref" "$cw_skill" >/dev/null 2>&1 && continue
    case " $cw_stale " in *" $s_name "*) ;; *) cw_stale="${cw_stale}${s_name} " ;; esac
  done
  if [ "$cw_seen" -eq 0 ]; then
    # COVERAGE FLOOR: a zero-file sweep and a zero-drift sweep are otherwise
    # indistinguishable, and printing a checkmark over an empty set is how the
    # overdue-TODO scan lied for two days.
    skip "no Cowork skill cache on disk to compare (nothing scanned — NOT a pass)"
  elif [ -n "$cw_stale" ]; then
    warn "Cowork skill(s) stale vs ~/.claude/skills: ${cw_stale%% } (scanned $cw_seen)" \
         "zip each as <name>/SKILL.md into <name>.skill and install it — per ACCOUNT. The cache is read-only and rebuilt from the account store, so cp does nothing, and uploading under one account does NOT fix another."
  else
    ok "Cowork skills match ~/.claude/skills ($cw_seen scanned)"
  fi
else
  warn "LIMITLESS_STACK_HOME ($LIMITLESS_STACK_HOME) not present — can't verify Limitless Stack sync" \
       "git clone https://github.com/Open-Scaffold-Labs/LimitlessStack.git \$HOME/LimitlessStack  (or set LIMITLESS_STACK_HOME)"
fi
echo ""

# ── [meta] Nightly self-heal (Loop 5 outer loop) ────────
# The scheduled outer loop (tools/nightly-selfheal.sh via launchd
# com.openscaffold.nightly-selfheal) runs THIS preflight unattended each night
# and auto-runs the deterministic correctors. Surface its last run here so a
# silently-broken nightly (Mac asleep for days, launchd unloaded, or a residual
# finding no corrector can fix) shows up at the NEXT session start instead of
# rotting unnoticed. Added 2026-07-23 with Loop 5.
echo "[meta] Shell safety (set -u static check)"
# Added 2026-08-24 (claude-anti-patterns #72). The pre-commit gate stops this
# class entering the repo and the nightly catches it at runtime — but a runtime
# check only ever sees the ONE BRANCH that executed. A bug sitting in a branch
# today's run does not take is invisible to every other layer and visible to
# this one, because static analysis reads all of them. That is why this exists
# in addition to, not instead of, the gate.
if [ -f "$VAULT/tools/shell-unbound-check.py" ]; then
  if shell_out="$(python3.11 "$VAULT/tools/shell-unbound-check.py" 2>&1)"; then
    ok "no unbound-variable risks in tools/*.sh ($(printf '%s' "$shell_out" | grep -c '✓') file(s) scanned)"
  else
    warn "unbound-variable risk in tools/*.sh — $(printf '%s\n' "$shell_out" | grep -cE '^      line ') site(s)" \
         "python3.11 tools/shell-unbound-check.py  ·  guard it, or mark the line '# unbound-ok: <why>'"
  fi
else
  warn "tools/shell-unbound-check.py missing — the set -u class is unguarded at author time" \
       "cp \"$LIMITLESS_STACK_HOME/tools/shell-unbound-check.py\" \"$VAULT/tools/\""
fi
echo ""

echo "[meta] Task files current?"
# Added 2026-08-24. Matt, on being shown that 385 "open" boxes contained 222
# already-shipped/ruled/not-a-task items: "so far it couldnt" be relied on.
# The rot was invisible because nothing ever looked: no session re-read an old
# box, and session write-ups were being filed into the task list itself (63% of
# Active was prose that already existed in wiki/log.md). This makes all of that
# visible EVERY Roll Call instead of once every four months.
if [ -f "$VAULT/tools/task-file-check.py" ]; then
  if task_out="$(python3.11 "$VAULT/tools/task-file-check.py" --quiet 2>&1)"; then
    ok "task files current (audited, no stale/duplicate/closed-section drift)"
  else
    while IFS= read -r tline; do
      [ -z "$tline" ] && continue
      warn "$(printf '%s' "$tline" | sed 's/^  ✗ //')" \
           "python3.11 tools/task-file-check.py  ·  tick what you shipped, archive closed sections, keep write-ups in wiki/log.md"
    done <<< "$task_out"
  fi
else
  warn "tools/task-file-check.py missing — task-file rot is unmonitored" \
       "cp \"$LIMITLESS_STACK_HOME/tools/task-file-check.py\" \"$VAULT/tools/\""
fi
echo ""

echo "[meta] Nightly self-heal (Loop 5)"
NSH_LABEL="com.openscaffold.nightly-selfheal"
NSH_PLIST="$HOME/Library/LaunchAgents/$NSH_LABEL.plist"
NSH_STATE="$VAULT/tools/.nightly-selfheal-state.json"
if [ ! -f "$NSH_PLIST" ]; then
  warn "nightly self-heal launchd job not installed" \
       "cp \"$VAULT/tools/$NSH_LABEL.plist\" ~/Library/LaunchAgents/ && launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/$NSH_LABEL.plist"
elif ! launchctl print "gui/$(id -u)/$NSH_LABEL" >/dev/null 2>&1; then
  warn "nightly self-heal launchd job installed but not loaded" \
       "launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/$NSH_LABEL.plist"
else
  ok "nightly self-heal launchd job loaded ($NSH_LABEL)"
fi
if [ -f "$NSH_STATE" ]; then
  NSH_LINE=$(python3 - "$NSH_STATE" <<'PY'
import json, sys, datetime
try:
    s = json.load(open(sys.argv[1]))
except Exception as e:
    print("PARSE\terror reading state: %s\t-" % e); sys.exit()
lr = s.get("last_run", "")
try:
    dt = datetime.datetime.strptime(lr, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    age_h = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
except Exception:
    age_h = 9999
verdict = s.get("final_verdict", "unknown")
resid = len(s.get("residual_findings", []))
corr = ",".join(s.get("correctors_run", [])) or "none"
healed = s.get("healed", False)
needs_human = s.get("needs_human", verdict != "ready")
# ACTIONABLE vs RESIDUAL. residual_findings holds EVERYTHING the run saw, including
# the states nightly-selfheal.sh's ACCEPTED_RE deliberately does not escalate. This
# readout used to print len(residual_findings), so a night with ONE real finding
# announced "5 residual finding(s)" and buried the one that mattered under four it
# had already decided were fine. Report what the classifier concluded, and NAME the
# finding — a count sends the reader to a file, a name lets them act. (2026-08-20)
actionable = s.get("actionable_findings")
has_field = actionable is not None
n_act = len(actionable) if has_field else None
first = (actionable[0][:150] if actionable else "")
if age_h > 30:
    print("STALE\tlast nightly self-heal was %.0fh ago (verdict=%s) — job may be broken or Mac asleep\tlaunchctl kickstart -k gui/$(id -u)/com.openscaffold.nightly-selfheal  (or check tools/logs/)" % (age_h, verdict))
elif needs_human and has_field and n_act == 0:
    # needs_human with nothing actionable means the two disagree. Say so plainly
    # rather than picking a side — a silent reconciliation here would hide a bug in
    # whichever one is wrong.
    print("NEEDHUMAN\tlast nightly self-heal set needs_human but published 0 actionable findings (verdict=%s, %d residual) — the flag and the list disagree\tcompare needs_human vs actionable_findings in tools/.nightly-selfheal-state.json" % (verdict, resid))
elif needs_human and has_field:
    print("NEEDHUMAN\tlast nightly self-heal: %d actionable finding(s) of %d residual, correctors=%s — first: %s\tsee tools/.nightly-selfheal-state.json + tools/logs/" % (n_act, resid, corr, first))
elif needs_human:
    print("NEEDHUMAN\tlast nightly self-heal ended %s with %d residual finding(s) (state file predates actionable_n — count may be inflated by known-accepted states), correctors=%s\tsee tools/.nightly-selfheal-state.json + tools/logs/" % (verdict, resid, corr))
elif verdict != "ready":
    print("OK\tlast nightly self-heal: READY* (%.0fh ago, %d known-accepted residual, correctors=%s)\t-" % (age_h, resid, corr))
else:
    tag = "HEALED->READY" if healed else "READY"
    print("OK\tlast nightly self-heal: %s (%.0fh ago, correctors=%s)\t-" % (tag, age_h, corr))
PY
)
  NSH_STATUS="${NSH_LINE%%$'\t'*}"
  NSH_REST="${NSH_LINE#*$'\t'}"
  NSH_MSG="${NSH_REST%%$'\t'*}"
  NSH_FIX="${NSH_REST##*$'\t'}"
  case "$NSH_STATUS" in
    OK)              ok   "$NSH_MSG" ;;
    STALE|NEEDHUMAN) warn "$NSH_MSG" "$NSH_FIX" ;;
    *)               warn "nightly self-heal state unreadable: $NSH_MSG" "rm $NSH_STATE  (next nightly rewrites it)" ;;
  esac
else
  skip "no nightly self-heal run recorded yet (state file absent)"
fi
echo ""

# ── [meta] Trust-anchor reality (Loop 6) ────────────────
# The CLAUDE.md files are the stack's trust anchors — every session reads them
# as ground truth, so silent doc/reality drift propagates as confidently-stated
# wrong facts (the #12/#14/#33 class). tools/trust-anchor-check.py mechanizes
# the checkable part of the end-of-session "refresh the trust anchors" step.
# SEVEN dimensions as of 2026-08-23 (was three): Hub migration table vs
# migrations/ files; the SAME parity check against README.md (a green on
# CLAUDE.md said nothing about the doc a new reader opens first); self-
# referential backtick file-path claims; notebook IDs vs the routing config;
# phantom routes (a sidebar LABEL cited as a path, derived from nav-config so
# the next divergence needs no code change); prose counts (N migrations / N
# routes vs the count on disk); and canonical facts (a registered fact restated
# without linking to its owner page). Conservative by design (only unambiguous
# drift) so it never cries wolf — two broader variants were prototyped and
# REJECTED on measured false positives; see the comments in the checker. Drift here is HUMAN-GATED — the
# nightly (Loop 5) surfaces/escalates it but never auto-edits a trust anchor.
# Added 2026-07-23 with Loop 6.
echo "[meta] Trust-anchor reality (Loop 6)"
if [ -r "$VAULT/tools/trust-anchor-check.py" ]; then
  TA_ERRF="/tmp/.ta_err.$$"
  TA_OUT=$(python3.11 "$VAULT/tools/trust-anchor-check.py" 2>"$TA_ERRF")
  TA_EXIT=$?
  TA_ERR=$(cat "$TA_ERRF" 2>/dev/null; rm -f "$TA_ERRF")
  if [ "$TA_EXIT" -eq 2 ]; then
    warn "trust-anchor check errored" "${TA_ERR:-see tools/trust-anchor-check.py}"
  else
    # Lines are either "SKIP: <reason>" (a dimension that couldn't run) or
    # "<message>\t<fix>" (a drift finding). here-string (not a pipe) so warn()
    # updates THIS shell's counters. The green line claims only what ran.
    ta_drift=0
    while IFS= read -r ta_line; do
      [ -z "$ta_line" ] && continue
      case "$ta_line" in
        SKIP:*) skip "trust-anchor ${ta_line#SKIP: }" ;;
        *)      warn "${ta_line%%$'\t'*}" "${ta_line#*$'\t'}"; ta_drift=1 ;;
      esac
    done <<< "$TA_OUT"
    [ "$ta_drift" -eq 0 ] && ok "trust anchors match reality (no drift in the checks that ran)"
  fi
else
  skip "trust-anchor-check.py not present — skipping Loop 6"
fi
echo ""

# ── [meta] Anti-pattern review (rec #5 self-trigger) ────
# The self-updating anti-patterns loop (rec #5) only fires when a session runs
# its inspector — a discipline-dependent gap (anti-pattern #1). This is the
# DETERMINISTIC trigger: it flags when mistake-bearing log entries have been
# written since the anti-patterns page was last reviewed, so the interactive
# session gets a nudge to run the inspector. Human/agent-gated (the inspection
# is an LLM step) — surfaced at Roll Call, but ADDED to the nightly's
# non-escalation allowlist so it never wakes Matt at 04:10. Added 2026-07-23.
echo "[meta] Anti-pattern review (rec #5 self-trigger)"
if [ -r "$VAULT/tools/anti-pattern-candidates.py" ]; then
  AP_OUT=$(python3.11 "$VAULT/tools/anti-pattern-candidates.py" --check-due 2>&1)
  AP_EXIT=$?
  if [ "$AP_EXIT" -eq 0 ]; then
    ok "$AP_OUT"
  elif [ "$AP_EXIT" -eq 1 ]; then
    warn "$AP_OUT" \
         "run the rec #5 inspector this session (gather + independent inspector subagent), stage proposals for Matt, then bump claude-anti-patterns.md anti_patterns_reviewed: (NOT updated: — that field is the page-edit date and bumping it used to silence this gate)"
  else
    skip "anti-pattern review check errored — $AP_OUT"
  fi
else
  skip "anti-pattern-candidates.py not present — skipping rec #5 trigger"
fi
echo ""

# ── [4/7] Pinecone ──────────────────────────────────────
echo "[4/7] Pinecone (semantic memory)"
if ! check_enabled "pinecone"; then
  echo "  ⊘ not enabled in this project's manifest (.limitless-project.py CHECKS) — skipping"
elif PINECONE_API_KEY_VAL="$(security find-generic-password -s pinecone-api-key -w 2>/dev/null || true)"; [ -z "$PINECONE_API_KEY_VAL" ]; then
  begin_tool "pinecone" "Pinecone" "Memory"
  bad "no Pinecone API key in Keychain" "security add-generic-password -s pinecone-api-key -a matt -w <key>"
else
  begin_tool "pinecone" "Pinecone" "Memory"
  PINECONE_STATS=$(PINECONE_API_KEY="$PINECONE_API_KEY_VAL" python3.11 -c "
import os, sys, json
try:
    from pinecone import Pinecone
    pc = Pinecone(api_key=os.environ['PINECONE_API_KEY'])
    s = pc.Index('openscaffold').describe_index_stats()
    print(json.dumps({'vectors': s.get('total_vector_count'), 'namespaces': list(s.get('namespaces', {}).keys())}))
except Exception as e:
    print(json.dumps({'error': str(e)}))
    sys.exit(1)
" 2>&1)
  if echo "$PINECONE_STATS" | grep -q '"error"'; then
    bad "Pinecone API error" "$PINECONE_STATS"
  else
    VECTORS=$(echo "$PINECONE_STATS" | python3.11 -c "import sys,json;print(json.load(sys.stdin).get('vectors',0))" 2>/dev/null)
    NSS=$(echo "$PINECONE_STATS" | python3.11 -c "import sys,json;print(','.join(json.load(sys.stdin).get('namespaces',[])))" 2>/dev/null)
    if [ "${VECTORS:-0}" -gt 100 ]; then
      ok "$VECTORS vectors · namespaces: [$NSS]"
    else
      warn "only ${VECTORS:-0} vectors in index" "run python3.11 tools/pinecone-sync.py"
    fi
  fi

  # Embedding quota probe — describe_index_stats succeeds on quota exhaustion
  # because it doesn't consume embedding tokens, so stats-only checks miss the
  # failure mode where both pinecone-sync AND pinecone-search are dead. This
  # 1-token test call catches RESOURCE_EXHAUSTED from the free-tier monthly
  # 5M embedding-token cap. Added 2026-04-20 after session discovered 429-loop
  # mid-task (see wiki/log.md schema entry).
  EMBED_PROBE=$(PINECONE_API_KEY="$PINECONE_API_KEY_VAL" python3.11 -c "
import os, sys, json
try:
    from pinecone import Pinecone
    pc = Pinecone(api_key=os.environ['PINECONE_API_KEY'])
    r = pc.inference.embed(
        model='multilingual-e5-large',
        inputs=['preflight'],
        parameters={'input_type': 'passage'}
    )
    vec = r.data[0]['values'] if r.data else []
    print(json.dumps({'ok': True, 'dim': len(vec)}))
except Exception as e:
    msg = str(e)
    exhausted = ('RESOURCE_EXHAUSTED' in msg) or ('token limit' in msg) or ('(429)' in msg)
    print(json.dumps({'error': msg[:400], 'exhausted': exhausted}))
    sys.exit(1)
" 2>&1)
  if echo "$EMBED_PROBE" | grep -q '"exhausted": *true'; then
    # Quota exhaustion is a known accepted state — pinecone-search + pinecone-sync
    # are non-functional until monthly reset, but session work can proceed without
    # them (the wiki is the primary source of truth; Pinecone is augmentation).
    # Treat as warn, not block. Original block-level treatment was too aggressive
    # for a recurring monthly cycle. (Updated 2026-04-29.)
    # 2026-08-20: demoted warn -> accepted. The text already said "accepting as
    # known state" while still counting as a drift finding, so every Roll Call and
    # every nightly opened with a yellow nobody could clear. CLAUDE.md is explicit
    # that this is Matt's account-level call and that sessions must not re-report
    # it ("it is in 30 log entries already"). Printing it without counting it is
    # what that instruction actually asks for.
    PINECONE_CAPPED=1
    accepted "Pinecone embedding quota exhausted (monthly cap hit) — known state, session may proceed" "account-level, Matt's to clear (upgrade or monthly reset). pinecone-search + pinecone-sync stay non-functional until then — see wiki/concepts/pinecone-warehouse.md"
  elif echo "$EMBED_PROBE" | grep -q '"error"'; then
    warn "Pinecone embedding probe failed (non-quota error)" "$EMBED_PROBE"
  elif echo "$EMBED_PROBE" | grep -q '"ok": *true'; then
    ok "embedding endpoint live (probe returned valid vector)"
  else
    warn "Pinecone embedding probe output unparseable" "$EMBED_PROBE"
  fi

  # Sync freshness — find the newest wiki file and see if it pre-dates the last sync log
  WIKI_NEWEST_TS=$(find "$VAULT/wiki" "$VAULT/CLAUDE.md" -name '*.md' -type f -exec stat -f '%m' {} \; 2>/dev/null | sort -n | tail -1)
  if [ -n "$WIKI_NEWEST_TS" ]; then
    WIKI_AGE_HOURS=$(( (NOW_TS - WIKI_NEWEST_TS) / 3600 ))
    if [ -f "$VAULT/tools/.pinecone-sync-state.json" ]; then
      LAST_SYNC_TS=$(stat -f '%m' "$VAULT/tools/.pinecone-sync-state.json" 2>/dev/null || echo 0)
      LAST_SYNC_AGE_HOURS=$(( (NOW_TS - LAST_SYNC_TS) / 3600 ))
      if [ "$LAST_SYNC_TS" -lt "$WIKI_NEWEST_TS" ]; then
        # Only a real finding when a sync is POSSIBLE. While the monthly cap is
        # exhausted this lag is the guaranteed consequence of the cap, and its old
        # remediation string told the reader to run pinecone-sync.py — a command
        # CLAUDE.md forbids in capital letters. A fix instruction that must not be
        # followed is worse than no instruction. (2026-08-20)
        if [ "${PINECONE_CAPPED:-0}" = "1" ]; then
          accepted "wiki has edits newer than last Pinecone sync (wiki ${WIKI_AGE_HOURS}h old, last sync ${LAST_SYNC_AGE_HOURS}h ago) — expected while the cap is exhausted" "NO ACTION: do not run pinecone-sync while over cap (CLAUDE.md checklist step 5). The corpus is stale; say so rather than reporting a 429 as 'no hits'."
        else
        warn "wiki has edits newer than last Pinecone sync (wiki ${WIKI_AGE_HOURS}h old, last sync ${LAST_SYNC_AGE_HOURS}h ago)" "python3.11 tools/pinecone-sync.py --changed-only"
        fi
      else
        ok "last sync newer than wiki edits (${LAST_SYNC_AGE_HOURS}h ago)"
      fi
    else
      warn "no pinecone-sync state file" "python3.11 tools/pinecone-sync.py --changed-only"
    fi
  fi
fi
echo ""

# ── [5/7] NotebookLM ────────────────────────────────────
echo "[5/7] NotebookLM (research desk + reminder layer)"
begin_tool "notebook" "NotebookLM" "Research"
if ! command -v notebooklm >/dev/null 2>&1; then
  bad "notebooklm CLI not installed" "pip install \"notebooklm-py[browser]\" && playwright install chromium && notebooklm login"
else
  # CLI version staleness — a stale notebooklm-py cannot complete Google's auth
  # handshake and then reports "auth failing", masking the true cause (a version
  # gap, not a bad login). Observed 2026-07-31: 0.3.4 installed vs 0.7.3 latest →
  # token_fetch failed with a WebLiteSignIn redirect; two clean logins could not
  # fix it, the upgrade did. Checked BEFORE auth so the fix hint points at the
  # real cause. Network-tolerant: silently skips if PyPI is unreachable.
  NBLM_STALE=0
  NBLM_INSTALLED=$(notebooklm --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  NBLM_LATEST=$(curl -s --max-time 5 https://pypi.org/pypi/notebooklm-py/json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null)
  if [ -n "$NBLM_INSTALLED" ] && [ -n "$NBLM_LATEST" ]; then
    if [ "$NBLM_INSTALLED" = "$NBLM_LATEST" ]; then
      ok "notebooklm CLI up to date ($NBLM_INSTALLED)"
    else
      # Only warn when installed actually sorts OLDER than latest (never on a
      # local dev build that's ahead of PyPI).
      NBLM_OLDER=$(printf '%s\n%s\n' "$NBLM_INSTALLED" "$NBLM_LATEST" | sort -V | head -1)
      if [ "$NBLM_OLDER" = "$NBLM_INSTALLED" ]; then
        NBLM_STALE=1
        warn "notebooklm CLI $NBLM_INSTALLED is behind latest $NBLM_LATEST — a stale CLI reports auth failures that are really a version gap" "pip3.11 install --upgrade notebooklm-py && notebooklm skill install"
      fi
    fi
  fi

  AUTH_OUT=$(notebooklm auth check --test 2>&1)
  # Transient token-fetch failures happen (observed 2026-06-10: BLOCK at 04:40,
  # auth valid on the next check) — retry once before declaring a blocker.
  # See anti-pattern #24.
  if echo "$AUTH_OUT" | grep -q "fail"; then
    sleep 5
    AUTH_OUT=$(notebooklm auth check --test 2>&1)
  fi
  if echo "$AUTH_OUT" | grep -q "Authentication Check" && ! echo "$AUTH_OUT" | grep -q "fail"; then
    ok "auth OK (storage_state.json valid, token fetch works)"
  elif echo "$AUTH_OUT" | grep -q "fail"; then
    if [ "$NBLM_STALE" -eq 1 ]; then
      bad "NotebookLM auth failing — CLI is stale ($NBLM_INSTALLED < $NBLM_LATEST), the LIKELY cause" "pip3.11 install --upgrade notebooklm-py && notebooklm skill install && notebooklm login — the version gap breaks Google's auth handshake; upgrade BEFORE re-logging in (2026-07-31)"
    else
      bad "NotebookLM auth failing" "invoke Skill(notebooklm), then notebooklm login — do NOT try in the sandbox"
    fi
  else
    warn "auth check output unparseable" "notebooklm auth check --test · invoke Skill(notebooklm) if unclear"
  fi

  # Notebook coverage — every notebook in NotebookLM must be in NOTEBOOK_ROUTES,
  # DEFAULT_ROUTE, REMINDER_NOTEBOOK_ID, or IGNORED_NOTEBOOKS. Catches the
  # "TheMatch silently unrouted" failure mode (2026-04-29). Single source of
  # truth lives in tools/notebooklm-wiki-refresh.py — this check shells out to
  # the --check-coverage flag rather than duplicating IDs in bash.
  COVERAGE_OUT=$(python3.11 "$VAULT/tools/notebooklm-wiki-refresh.py" --check-coverage --skip-auth-check 2>&1)
  COVERAGE_EXIT=$?
  if [ "$COVERAGE_EXIT" -eq 0 ]; then
    ok "notebook coverage: all NotebookLM notebooks routed or explicitly ignored"
  elif [ "$COVERAGE_EXIT" -eq 1 ]; then
    # Each line: "ID<TAB>title". Emit one warn per orphan so each gets its own fix command.
    while IFS=$'\t' read -r orphan_id orphan_title; do
      [ -z "$orphan_id" ] && continue
      warn "notebook \"$orphan_title\" ($orphan_id) not in routing or ignore list" \
           "add to NOTEBOOK_ROUTES or IGNORED_NOTEBOOKS in tools/notebooklm-wiki-refresh.py"
    done <<< "$COVERAGE_OUT"
  else
    warn "notebook coverage check failed (exit=$COVERAGE_EXIT)" "$COVERAGE_OUT"
  fi

  # Notebook capacity — warn BEFORE a routed notebook silently hits the
  # 50-source Standard-tier cap. At the cap, `source add` fails with an
  # opaque "Failed to get SOURCE_ID from registration response" error —
  # hit on the-match's default bucket 2026-07-06 (50/50). Threshold: 47.
  # 2026-08-21 (Matt-approved): launched in the BACKGROUND and joined after
  # the dedupe sweep below. This check fetches the same per-notebook source
  # listings the sweep fetches; running the two serially (14.5s + 61.8s
  # measured) put the whole preflight (~105s cold) past Cowork's ~60s
  # tool-call cap, which made Roll Call look hung from a session — it never
  # was; the timed-out call kept running and exited WARN. Only the FETCH
  # overlaps: the ok/warn interpretation happens at the join in the main
  # shell, because counter increments would not propagate out of a
  # background job. Output-order note: the capacity verdict line now prints
  # after the dedupe-sweep line instead of before the freshness block.
  CAPS_TMP=$(mktemp /tmp/preflight-caps.XXXXXX)
  python3.11 "$VAULT/tools/notebooklm-wiki-refresh.py" --check-caps --skip-auth-check > "$CAPS_TMP" 2>&1 &
  CAPS_BG_PID=$!

  # Per-project notebook freshness — each routed file compared against its route's state file.
  # Routes come from the project manifest's NOTEBOOKLM.routes list. Empty routes
  # (the-match, simple verticals) → loop runs 0 iterations.
  # Backwards-compat: no manifest → use Hub-vault hardcoded list.
  if [ -n "$LIMITLESS_PROJECT_ROUTES" ] || [ -f "$VAULT/.limitless-project.py" ]; then
    _ROUTE_LIST="$LIMITLESS_PROJECT_ROUTES"
  else
    _ROUTE_LIST="firehazmat:wiki/apps/firehazmat.md openchiropractor:wiki/apps/openchiropractor.md openfirehouse:wiki/apps/openfirehouse.md opensalon:wiki/apps/opensalon.md the-match:wiki/apps/the-match.md"
  fi
  # Report ONE line per LABEL, not per route. Several routes legitimately share
  # a label (openfirehouse has 10 path prefixes, hub has 8) and they all compare
  # against that label's single state file — so a per-route loop emitted 10
  # identical "mirror in sync" lines with the same age. That padded Roll Call's
  # output with ~18 redundant greens, which is how a real finding gets skimmed
  # past. Detection is unchanged: we take the NEWEST routed file per label,
  # which is exactly the one that decides staleness. bash 3.2 on macOS has no
  # associative arrays, hence the two-pass string approach. Fixed 2026-08-03.
  _SEEN_LABELS=""
  for route in $_ROUTE_LIST; do
    label="${route%%:*}"
    case " $_SEEN_LABELS " in *" $label "*) continue ;; esac
    _SEEN_LABELS="$_SEEN_LABELS $label"

    state_path="$VAULT/tools/.notebooklm-${label}-state.json"
    if [ ! -f "$state_path" ]; then
      warn "no notebooklm $label state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only $label"
      continue
    fi
    STATE_TS=$(stat -f '%m' "$state_path" 2>/dev/null || echo 0)

    # Newest routed file for this label across every route that shares it.
    NEWEST_TS=0; NEWEST_FILE=""; ROUTED_ANY=false
    for r2 in $_ROUTE_LIST; do
      [ "${r2%%:*}" = "$label" ] || continue
      f2="${r2#*:}"
      t2="$VAULT/$f2"
      [ -f "$t2" ] || continue          # missing on disk — other checks cover it
      ROUTED_ANY=true
      ts2=$(stat -f '%m' "$t2" 2>/dev/null || echo 0)
      if [ "$ts2" -gt "$NEWEST_TS" ]; then NEWEST_TS="$ts2"; NEWEST_FILE="$f2"; fi
    done
    $ROUTED_ANY || continue

    AGE_HOURS=$(( (NOW_TS - STATE_TS) / 3600 ))
    if [ "$NEWEST_TS" -gt "$STATE_TS" ]; then
      warn "notebooklm $label mirror stale ($NEWEST_FILE edited since last refresh, ${AGE_HOURS}h ago)" "python3.11 tools/notebooklm-wiki-refresh.py --only $label"
    else
      ok "notebooklm $label mirror in sync (${AGE_HOURS}h since refresh)"
    fi
  done

  # Hub route (ca083f4f) — filename-prefix route, not a single file. Finds the
  # newest wiki/synthesis/hub-*.md file and compares to the hub state file.
  # Only run this check if 'hub' is in the project's routes — Hub-vault-specific.
  HUB_STATE="$VAULT/tools/.notebooklm-hub-state.json"
  _HAS_HUB_ROUTE=false
  if echo " $LIMITLESS_PROJECT_ROUTES " | grep -q ' hub:'; then
    _HAS_HUB_ROUTE=true
  fi
  # Backwards-compat: if no manifest, assume Hub-vault layout (has hub route)
  if [ ! -f "$VAULT/.limitless-project.py" ]; then
    _HAS_HUB_ROUTE=true
  fi
  # This hub block predates the generic per-route loop above and uses a glob
  # (wiki/synthesis/hub-*.md) rather than the manifest routes. When a manifest
  # IS present the loop already reported the hub label, so running this too
  # printed the same verdict twice. Kept for the no-manifest fallback, where
  # the hardcoded _ROUTE_LIST has no hub entry and this is the only hub check.
  case " ${_SEEN_LABELS:-} " in
    *" hub "*) _HAS_HUB_ROUTE=false ;;   # already reported by the loop
  esac
  if ! $_HAS_HUB_ROUTE; then
    : # skip hub route check — project doesn't have one, or the loop covered it
  elif [ ! -f "$HUB_STATE" ]; then
    warn "no notebooklm hub state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only hub"
  else
    HUB_NEWEST_TS=$(find "$VAULT/wiki/synthesis" -name 'hub-*.md' -type f -exec stat -f '%m' {} \; 2>/dev/null | sort -n | tail -1)
    if [ -n "$HUB_NEWEST_TS" ]; then
      HUB_STATE_TS=$(stat -f '%m' "$HUB_STATE" 2>/dev/null || echo 0)
      HUB_AGE_HOURS=$(( (NOW_TS - HUB_STATE_TS) / 3600 ))
      if [ "$HUB_NEWEST_TS" -gt "$HUB_STATE_TS" ]; then
        warn "notebooklm hub mirror stale (a wiki/synthesis/hub-*.md edited since last refresh, ${HUB_AGE_HOURS}h ago)" "python3.11 tools/notebooklm-wiki-refresh.py --only hub"
      else
        ok "notebooklm hub mirror in sync (${HUB_AGE_HOURS}h since refresh)"
      fi
    fi
  fi

  # Default-bucket (cdaa7a43) freshness — newest non-routed wiki file vs the wiki state file.
  # WIKI_DEFAULT_NEWEST_TS excludes files routed elsewhere (per-project + hub) AND files in
  # EXCLUDE_FROM_NOTEBOOKS, so we don't falsely warn cdaa7a43 is stale when the most-recent
  # edit went somewhere cdaa7a43 doesn't own. Keep this list in sync with NOTEBOOK_ROUTES +
  # EXCLUDE_FROM_NOTEBOOKS in tools/notebooklm-wiki-refresh.py.
  WIKI_DEFAULT_NEWEST_TS=$(find "$VAULT/wiki" -name '*.md' -type f \
    ! -path "$VAULT/wiki/apps/firehazmat.md" \
    ! -path "$VAULT/wiki/apps/openchiropractor.md" \
    ! -path "$VAULT/wiki/apps/openfirehouse.md" \
    ! -path "$VAULT/wiki/apps/opensalon.md" \
    ! -path "$VAULT/wiki/apps/the-match.md" \
    ! -path "$VAULT/wiki/synthesis/hub-*.md" \
    ! -path "$VAULT/wiki/sources/firehazmat-*.md" \
    ! -path "$VAULT/wiki/sources/openchiropractor-*.md" \
    ! -path "$VAULT/wiki/sources/openfirehouse-*.md" \
    ! -path "$VAULT/wiki/sources/opensalon-*.md" \
    -exec stat -f '%m' {} \; 2>/dev/null | sort -n | tail -1)
  if [ -f "$VAULT/tools/.notebooklm-wiki-state.json" ]; then
    LAST_REFRESH_TS=$(stat -f '%m' "$VAULT/tools/.notebooklm-wiki-state.json" 2>/dev/null || echo 0)
    LAST_REFRESH_AGE_HOURS=$(( (NOW_TS - LAST_REFRESH_TS) / 3600 ))
    if [ -n "$WIKI_DEFAULT_NEWEST_TS" ] && [ "$LAST_REFRESH_TS" -lt "$WIKI_DEFAULT_NEWEST_TS" ]; then
      # An mtime comparison cannot see the notebook. It proves a file was touched
      # after the state file was written — NOT that content is missing upstream.
      #
      # The end-of-session order guarantees this fires: refresh the bucket, THEN
      # append this session's entry to wiki/log.md. Verified 2026-08-20 — refresh
      # at 11:27, log.md at 11:29, and asking cdaa7a43 directly returned PRESENT
      # for both of that day's entries including the file's LAST one. Reported as
      # drift, that 2-minute ordering artifact is what sent a session into eight
      # re-uploads of a 1.19 MB file that had already landed (CLAUDE.md step 7).
      #
      # So: a lag measured in minutes-to-hours is the normal wrap order and is
      # informational. A lag over ONE DAY means a session ended without refreshing
      # at all, which is real drift. The boundary is a heuristic — stated here so
      # the next reader can move it knowing what it was chosen against.
      # Either way the remediation is VERIFY, never a blind re-upload. (2026-08-20)
      EDIT_LAG_HOURS=$(( (WIKI_DEFAULT_NEWEST_TS - LAST_REFRESH_TS) / 3600 ))
      if [ "$EDIT_LAG_HOURS" -lt 24 ]; then
        accepted "notebooklm wiki default bucket (cdaa7a43): wiki edits postdate the last refresh by ${EDIT_LAG_HOURS}h — normal end-of-session order, not evidence of absence" "if you need certainty: python3.11 tools/notebooklm-wiki-refresh.py --only wiki --verify-existing (no uploads), or ask the notebook directly. Do NOT re-upload on an mtime alone."
      else
        warn "notebooklm wiki default bucket (cdaa7a43) has edits ${EDIT_LAG_HOURS}h newer than last refresh (${LAST_REFRESH_AGE_HOURS}h ago) — a session likely ended without refreshing" "python3.11 tools/notebooklm-wiki-refresh.py --only wiki --verify-existing   # verify FIRST; retry cap two"
      fi
    else
      ok "notebooklm wiki default bucket (cdaa7a43) in sync (${LAST_REFRESH_AGE_HOURS}h since refresh)"
    fi
  else
    warn "no notebooklm-wiki default bucket state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only wiki"
  fi

  # Reminder-notebook ab4b7ccb source freshness. TWO-LEVEL CHECK as of
  # 2026-04-24 (after discovering notebooklm-wiki-refresh.py's cmd_refresh
  # was a no-op for file sources for weeks — see anti-pattern #11/#12 + log):
  #   1. mtime comparison — does the state file look newer than the source files?
  #      Catches the "wiki was edited but refresh hasn't run yet" case.
  #   2. verified_at comparison — does each source have a recent verified_at
  #      timestamp AND does it post-date the local file's mtime? Catches the
  #      "refresh ran but didn't actually replace content" failure mode that
  #      mtime alone misses.
  # Both levels look at the same 5 curated sources (CLAUDE.md,
  # synthesis/claude-anti-patterns.md, concepts/limitless-stack.md,
  # concepts/paperclip.md, apps/limitless-stack-hub.md).
  REMINDER_STATE="$VAULT/tools/.notebooklm-reminder-state.json"
  AB_STALE=0
  AB_UNVERIFIED=0
  if [ -f "$REMINDER_STATE" ]; then
    # Reminder file list comes from the manifest's NOTEBOOKLM.reminder.files.
    # Backwards-compat: no manifest → use Hub-vault's hardcoded 5-file list.
    if [ -n "$LIMITLESS_REMINDER_FILES" ] || [ -f "$VAULT/.limitless-project.py" ]; then
      _REMINDER_FILE_LIST="$LIMITLESS_REMINDER_FILES"
    else
      _REMINDER_FILE_LIST="CLAUDE.md wiki/synthesis/claude-anti-patterns.md wiki/concepts/limitless-stack.md wiki/concepts/paperclip.md wiki/apps/limitless-stack-hub.md"
    fi
    for rel in $_REMINDER_FILE_LIST; do
      f="$VAULT/$rel"
      [ -f "$f" ] || continue
      FILE_TS=$(stat -f '%m' "$f" 2>/dev/null || echo 0)

      # Pull the state entry's verified_at (may be missing if never verified,
      # or if the last sync's verify step failed — both should warn).
      VERIFIED_AT=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    e = d.get(sys.argv[2], {})
    v = e.get('verified_at')
    print(int(v) if v else 0)
except Exception:
    print(0)
" "$REMINDER_STATE" "$rel" 2>/dev/null)
      VERIFIED_AT=${VERIFIED_AT:-0}

      if [ "$VERIFIED_AT" -eq 0 ]; then
        AB_UNVERIFIED=$((AB_UNVERIFIED+1))
      elif [ "$VERIFIED_AT" -lt "$FILE_TS" ]; then
        # File was edited after the last successful content verification
        AB_STALE=$((AB_STALE+1))
      fi
    done

    # Use the manifest's reminder notebook ID short-prefix for the label,
    # falling back to "ab4b7ccb" for backwards-compat (Hub vault has no manifest).
    _REMINDER_LABEL="${LIMITLESS_REMINDER_NB_ID:0:8}"
    [ -z "$_REMINDER_LABEL" ] && _REMINDER_LABEL="ab4b7ccb"
    if [ "$AB_STALE" -gt 0 ] && [ "$AB_UNVERIFIED" -gt 0 ]; then
      bad "$_REMINDER_LABEL reminder notebook: $AB_STALE source(s) edited since last verify + $AB_UNVERIFIED never verified" "python3.11 tools/notebooklm-wiki-refresh.py --force --only reminder  (then --verify-existing)"
    elif [ "$AB_STALE" -gt 0 ]; then
      warn "$_REMINDER_LABEL reminder notebook: $AB_STALE source(s) edited since last verified upload" "python3.11 tools/notebooklm-wiki-refresh.py --force --only reminder"
    elif [ "$AB_UNVERIFIED" -gt 0 ]; then
      warn "$_REMINDER_LABEL reminder notebook: $AB_UNVERIFIED source(s) have no verified_at timestamp" "python3.11 tools/notebooklm-wiki-refresh.py --verify-existing --only reminder"
    else
      ok "$_REMINDER_LABEL reminder notebook sources content-verified"
    fi
  else
    warn "no reminder-notebook state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only reminder"
  fi

  # Duplicate-source audit across ALL 7 notebooks — added 2026-04-26 PM
  # after the original single-cdaa7a43 check (which was reporting clean
  # for weeks while ab4b7ccb and ca083f4f were silently accumulating 13
  # duplicates between them — caught by an end-of-session manual sweep).
  # Each `notebooklm source list` call measured 2-4s in isolation but
  # ~7.5s under the preflight's own back-to-back request pressure
  # (timed 2026-08-21: 61.8s for 8 serial calls) — which is why the fetch
  # phase below runs all notebooks concurrently, capped by the slowest
  # single call. Worth it: this is the layer Claude reads at the
  # start of every session, and stale reminder content has cost real
  # debugging time before (see anti-pattern #12).
  if command -v python3.11 >/dev/null 2>&1; then
    # Notebook id → state-label mapping for the suggested dedupe command.
    # Keep in sync with NOTEBOOK_ROUTES in tools/notebooklm-wiki-refresh.py
    # plus the reminder + default-wiki buckets.
    # Notebooks to dedupe-sweep come from the manifest. Backwards-compat:
    # no manifest → use Hub-vault hardcoded list.
    if [ -n "$LIMITLESS_DEDUPE_NOTEBOOKS" ] || [ -f "$VAULT/.limitless-project.py" ]; then
      notebooks="$LIMITLESS_DEDUPE_NOTEBOOKS"
    else
      notebooks="cdaa7a43:wiki ab4b7ccb:reminder f376f6e8:firehazmat 26a8db12:openchiropractor 9c8f3df0:openfirehouse 0a072ead:opensalon ca083f4f:hub e9337dea:the-match"
    fi
    sweep_total=0
    sweep_dirty=""
    sweep_skipped=0
    # Fetch phase (parallel, 2026-08-21): every notebook's listing lands in
    # its own temp file; the counting loop below then reads the files. Each
    # fetch also records its exit code in a sidecar file — nonzero routes
    # that notebook to the skipped tally BEFORE the JSON is read (see the
    # audit note at the counter: the CLI can fail while emitting parseable
    # error-JSON, which would otherwise count as clean). Explicit --notebook ids
    # (never `use`, see the 2026-08-03 note in the counting loop) are what
    # make concurrent calls safe. We wait on the fetch pids ONLY — a bare
    # `wait` would also reap the backgrounded capacity check and break its
    # join below.
    SWEEP_DIR=$(mktemp -d /tmp/preflight-sweep.XXXXXX)
    SWEEP_PIDS=""
    for entry in $notebooks; do
      nb_id="${entry%%:*}"
      nb_label="${entry##*:}"
      ( notebooklm source list --notebook "$nb_id" --json > "$SWEEP_DIR/$nb_label.json" 2>/dev/null; echo $? > "$SWEEP_DIR/$nb_label.exit" ) &
      SWEEP_PIDS="$SWEEP_PIDS $!"
    done
    for _pid in $SWEEP_PIDS; do wait "$_pid" 2>/dev/null; done
    for entry in $notebooks; do
      nb_id="${entry%%:*}"
      nb_label="${entry##*:}"
      # Count only what notebooklm-dedupe.py would actually delete. A shared
      # TITLE is not a duplicate: two different wiki pages can share a
      # basename (this vault has wiki/index.md AND
      # wiki/app-creation-reminders/index.md, both uploading as 'index.md').
      # Title-only counting reported that pair as a duplicate and pointed at
      # --apply, which would have deleted a live page's source and repointed
      # its state entry at the OTHER page — silent permanent staleness
      # (2026-08-03). Sources claimed by DIFFERENT state paths are a
      # collision, never a duplicate; only unclaimed ghosts are deletable.
      # --notebook, NOT `use`: `use` mutates a single shared context file, so
      # this very loop repoints it 8 times and any concurrent process (a
      # session running the deduper, the nightly self-heal) can read the wrong
      # bucket. Proven live 2026-08-03. Explicit ids are also what the CLI's
      # own docs prescribe for parallel workflows.
      # Audit fault-injection (2026-08-21) caught this: the CLI can FAIL
      # (exit 1) while still emitting parseable {'error': true} JSON on
      # stdout — json.load parses it, finds no 'sources', and a notebook we
      # never actually listed counts as CLEAN (0) instead of skipped. The
      # hole predates the parallel fetch: the old inline pipe discarded the
      # CLI's exit code the same way (verified — the bogus-id case printed
      # 0 through both forms). The sidecar exit code is the authoritative
      # signal, checked before the JSON is looked at; a missing sidecar
      # (fetch job killed) also routes to skipped.
      FETCH_EXIT=$(cat "$SWEEP_DIR/$nb_label.exit" 2>/dev/null || echo 1)
      if [ "$FETCH_EXIT" != "0" ]; then
        DUPE_COUNT=-1
      else
      DUPE_COUNT=$(python3.11 -c "
import json, sys, pathlib
from collections import defaultdict
try:
    d = json.load(sys.stdin)
    s = d if isinstance(d, list) else d.get('sources', [])
    claims = {}
    p = pathlib.Path(sys.argv[1])
    if p.exists():
        for rel, entry in json.loads(p.read_text()).items():
            sid = entry.get('source_id') if isinstance(entry, dict) else None
            if sid:
                claims[sid] = rel
    by_title = defaultdict(list)
    for src in s:
        by_title[src.get('title')].append(src)
    total = 0
    for title, group in by_title.items():
        if len(group) < 2:
            continue
        owners = {claims[g.get('id')] for g in group if claims.get(g.get('id'))}
        if len(owners) > 1:
            continue
        total += len(group) - 1
    print(total)
except Exception:
    print(-1)
" "$VAULT/tools/.notebooklm-$nb_label-state.json" < "$SWEEP_DIR/$nb_label.json" 2>/dev/null || echo -1)
      fi
      if [ "$DUPE_COUNT" = "-1" ] || [ -z "$DUPE_COUNT" ]; then
        # CLI unavailable / parse failed for this notebook — count toward
        # the skipped tally so the summary line reflects coverage gaps.
        sweep_skipped=$((sweep_skipped + 1))
      elif [ "$DUPE_COUNT" -gt 0 ]; then
        sweep_total=$((sweep_total + DUPE_COUNT))
        # Report each dirty notebook on its own warn line so the suggested
        # fix command names the right --notebook + --state. One-warn-per-
        # affected-bucket reads better in the verdict block than a single
        # rolled-up warning would.
        # The --verify-existing follow-up is part of the remediation, not an
        # optional extra: a dedupe survivor is the newest copy in the NOTEBOOK,
        # which need not be current with the file on disk, and the state entry
        # the dedupe repoints carries no verified_at. wiki/log.md:7591 recorded
        # that on 2026-08-18 and it lived nowhere a reader would meet it.
        warn "notebooklm $nb_id ($nb_label) has $DUPE_COUNT duplicate source(s)" \
             "python3.11 tools/notebooklm-dedupe.py --notebook $nb_id --state $nb_label  (dry-run first, then --apply) THEN python3.11 tools/notebooklm-wiki-refresh.py --only $nb_label --verify-existing"
        sweep_dirty="${sweep_dirty}${nb_id} "
      fi
    done
    if [ -z "$sweep_dirty" ] && [ "$sweep_skipped" -eq 0 ]; then
      ok "notebooklm dedupe sweep: 0 duplicates across 8 notebooks"
    elif [ -z "$sweep_dirty" ] && [ "$sweep_skipped" -gt 0 ]; then
      ok "notebooklm dedupe sweep: 0 duplicates across $((8 - sweep_skipped))/8 notebooks ($sweep_skipped skipped)"
    fi
    # If sweep_dirty is non-empty, individual warns above already covered it.
    rm -rf "$SWEEP_DIR"
  fi

  # Join the capacity check backgrounded before the freshness block
  # (2026-08-21). Interpretation lives HERE, in the main shell — ok/warn
  # counter increments would not survive a background subshell. Guarded so
  # a manifest path that skipped the launch cannot hit an unset pid.
  if [ -n "${CAPS_BG_PID:-}" ]; then
    wait "$CAPS_BG_PID" && CAPS_EXIT=0 || CAPS_EXIT=$?
    CAPS_OUT=$(cat "$CAPS_TMP" 2>/dev/null)
    rm -f "$CAPS_TMP"
    if [ "$CAPS_EXIT" -eq 0 ]; then
      ok "notebook capacity: all routed notebooks under the near-cap threshold (47/50)"
    elif [ "$CAPS_EXIT" -eq 1 ]; then
      while IFS=$'\t' read -r cap_id cap_label cap_count cap_cap; do
        [ -z "$cap_id" ] && continue
        # Report COVERAGE, not just the cap. "48/50 sources" reads as a tidy
        # housekeeping note; what it actually meant on 2026-08-24 was that 47
        # of the 95 pages routed to this bucket had NEVER made it in, so every
        # NotebookLM query against it was searching half the wiki and saying so
        # nowhere. A number that sounds fine while hiding the real one is the
        # same failure as an abort exiting 1 (claude-anti-patterns #72).
        # ELIGIBLE = routed MINUS the deliberate EXCLUDE_FROM_NOTEBOOKS list.
        # Excluding those is a design decision with a written rationale, not a
        # gap — counting them as "missing" turned a healthy bucket into a false
        # alarm on 2026-08-24 (reported 47 missing; the true number was 1).
        cap_routed=$(python3.11 "$VAULT/tools/notebooklm-wiki-refresh.py" --count-routed "$cap_label" 2>/dev/null || echo "")
        if [ -n "$cap_routed" ] && [ "$cap_routed" -gt "$cap_count" ] 2>/dev/null; then
          warn "notebook '$cap_label' ($cap_id) at $cap_count/$cap_cap sources — $((cap_routed - cap_count)) eligible page(s) not yet in it ($cap_count of $cap_routed)" \
               "run the refresh for this bucket; if the add fails, the cap is the blocker — raise the plan, split the bucket, or exclude more paths"
        else
          warn "notebook '$cap_label' ($cap_id) at $cap_count/$cap_cap sources — adds fail at the cap" \
               "consolidate or exclude sources (see the handoffs-rollup pattern, the-match 2026-07-06)"
        fi
      done <<< "$CAPS_OUT"
    else
      warn "notebook capacity check failed (exit=$CAPS_EXIT)" "$CAPS_OUT"
    fi
  fi
fi
echo ""

# ── [6/7] Antigravity ───────────────────────────────────
echo "[6/7] Antigravity (multi-model IDE)"
begin_tool "antigravity" "Antigravity" "IDE"
skip "not session-critical for Cowork agents; Matt's local IDE"
echo ""

# ── [6b] Hermes (agent runtime) ─────────────────────────
# Added 2026-07-21 (spec F-8): the Hub Workspace's persistent agent on Fly.
# /health is unauthenticated; /health/detailed (disk, gateway, model checks)
# needs the API_SERVER_KEY from the macOS Keychain. A suspended machine
# cold-wakes on the first request — that's expected, not a failure.
echo "[6b] Hermes (agent runtime — Hub Workspace)"
begin_tool "hermes" "Hermes" "Agent runtime"
HERMES_URL="${HERMES_HEALTH_URL:-https://openscaffold-hermes.fly.dev}"
HERMES_HEALTH=$(curl -s -m 30 "$HERMES_URL/health" 2>/dev/null)
if echo "$HERMES_HEALTH" | grep -q '"status": *"ok"'; then
  HERMES_VER=$(echo "$HERMES_HEALTH" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')
  ok "hermes gateway healthy (v${HERMES_VER:-?}) at $HERMES_URL"
  HERMES_KEY=$(security find-generic-password -s hermes-api-server-key-2026-07-20 -w 2>/dev/null)
  if [ -n "$HERMES_KEY" ]; then
    HERMES_DET=$(curl -s -m 30 -H "Authorization: Bearer $HERMES_KEY" "$HERMES_URL/health/detailed" 2>/dev/null)
    HERMES_DISK=$(echo "$HERMES_DET" | sed -n 's/.*"used_percent": *\([0-9.]*\).*/\1/p')
    if [ -n "$HERMES_DISK" ]; then
      HERMES_DISK_INT=${HERMES_DISK%.*}
      if [ "${HERMES_DISK_INT:-0}" -ge 80 ]; then
        warn "hermes volume at ${HERMES_DISK}% (threshold 80%) — sessions/skills/memory growth" \
             "fly volumes extend on openscaffold-hermes, or prune old sessions"
      else
        ok "hermes volume at ${HERMES_DISK}% used"
      fi
    else
      warn "hermes /health/detailed gave no disk metric — check auth or API drift" \
           "curl -H \"Authorization: Bearer \$(security find-generic-password -s hermes-api-server-key-2026-07-20 -w)\" $HERMES_URL/health/detailed"
    fi
  else
    skip "hermes disk check skipped — hermes-api-server-key-2026-07-20 not in this Mac's Keychain"
  fi
else
  warn "hermes gateway not healthy at $HERMES_URL (suspended cold-wake can take a few s — rerun once before escalating)" \
       "fly status -a openscaffold-hermes && fly logs -a openscaffold-hermes"
fi
echo ""

# ── [7/7] Paperclip ─────────────────────────────────────
# Real check since 2026-07-21 (deployed 2026-04-20; the old "deployment in
# progress" skip was 3 months stale — found during the F-8 monitoring pass).
echo "[7/7] Paperclip (agent coordination)"
begin_tool "paperclip" "Paperclip" "Coordination"
PAPERCLIP_URL="${PAPERCLIP_HEALTH_URL:-https://paperclip-prod.fly.dev}"
PAPERCLIP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 30 "$PAPERCLIP_URL/health" 2>/dev/null)
if [ "$PAPERCLIP_CODE" = "200" ]; then
  ok "paperclip healthy (HTTP 200) at $PAPERCLIP_URL"
else
  warn "paperclip /health returned HTTP ${PAPERCLIP_CODE:-none} at $PAPERCLIP_URL" \
       "fly status -a paperclip-prod (Dale's org access) · check the Hub /agents page"
fi
echo ""

# ── End of numbered tool sections — seal the last [7/7] tool so any
# subsequent checks (anti-patterns, session-bootstrap reminders) don't
# bleed into Paperclip's health string on the Hub's /today card.
finalize_tool

# ── Anti-patterns reminder ──────────────────────────────
# Mechanical safeguard against anti-pattern #1 ("skipping the 4-tool lookup /
# NotebookLM query before answering"). Surfaces the current anti-patterns
# inline so they're in context even if the ab4b7ccb NotebookLM query is
# skipped. Titles only — full text lives in the file and in NotebookLM for
# synthesis queries.
# Self-improvement: when Matt catches a new anti-pattern and a numbered entry
# is added to the file, this check picks it up automatically next run.
echo "Anti-patterns reminder (mechanical safeguard against skipping NotebookLM)"
ANTIPATTERNS_FILE="$VAULT/wiki/synthesis/claude-anti-patterns.md"
if [ -r "$ANTIPATTERNS_FILE" ]; then
  AP_COUNT=$(grep -c '^### [0-9]' "$ANTIPATTERNS_FILE" 2>/dev/null || echo 0)
  if [ "$AP_COUNT" -gt 0 ]; then
    AP_TS=$(stat -f '%m' "$ANTIPATTERNS_FILE" 2>/dev/null || echo 0)
    AP_AGE_DAYS=$(( (NOW_TS - AP_TS) / 86400 ))
    # Tuned 2026-05-03: "reviewed before substantive work" really means
    # "the reminder bucket Claude queries at session start has the latest
    # version". If the reminder layer's verified_at for this file is
    # newer than the file's mtime, the curated layer is current and the
    # warn is noise. Only warn if the file changed AND the reminder
    # bucket hasn't been re-verified since.
    AP_REL="wiki/synthesis/claude-anti-patterns.md"
    AP_VERIFIED_AT=0
    if [ -f "$REMINDER_STATE" ]; then
      AP_VERIFIED_AT=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    v = d.get(sys.argv[2], {}).get('verified_at')
    print(int(v) if v else 0)
except Exception:
    print(0)
" "$REMINDER_STATE" "$AP_REL" 2>/dev/null)
      AP_VERIFIED_AT=${AP_VERIFIED_AT:-0}
    fi
    if [ "$AP_AGE_DAYS" -gt 7 ]; then
      ok "$AP_COUNT anti-patterns on file (last edit ${AP_AGE_DAYS}d ago)"
    elif [ "$AP_VERIFIED_AT" -ge "$AP_TS" ]; then
      ok "$AP_COUNT anti-patterns on file (edited ${AP_AGE_DAYS}d ago, reminder bucket re-verified after edit)"
    else
      warn "anti-patterns file edited ${AP_AGE_DAYS}d ago and reminder bucket not re-verified since — review before substantive work" "read $ANTIPATTERNS_FILE or run python3.11 tools/notebooklm-wiki-refresh.py --only reminder"
    fi
    # The retrieval index at the top of the page is GENERATED from these
    # headings, and every entry must be routed by at least one §1 situation row.
    # Added 2026-08-07: without this, a new entry can be appended and never
    # indexed — the page grows while the thing a session actually reads does not.
    if [ -f "$VAULT/tools/anti-pattern-index.py" ]; then
      AP_IDX_OUT=$(cd "$VAULT" && python3.11 tools/anti-pattern-index.py --check 2>&1)
      if [ $? -eq 0 ]; then
        ok "anti-pattern retrieval index in sync (every entry routed)"
      else
        warn "anti-pattern index drift: $(echo "$AP_IDX_OUT" | head -2 | tr '\n' ' ')" \
             "cd \"$VAULT\" && python3.11 tools/anti-pattern-index.py   (add new entries to SITUATIONS first)"
      fi
    fi
    echo ""
    echo "  Active anti-patterns (titles only — full text: wiki/synthesis/claude-anti-patterns.md):"
    grep '^### [0-9]' "$ANTIPATTERNS_FILE" | sed 's/^### /    - #/'
  else
    warn "anti-patterns file present but has no numbered entries" "verify heading format: '### N. Title'"
  fi
else
  bad "anti-patterns file missing" "expected at $ANTIPATTERNS_FILE"
fi
echo ""

# ── Own-runtime watchdog ────────────────────────────────
# Added 2026-08-21 per the Roll Call self-improvement rule, the same day the
# preflight was found to have outgrown Cowork's ~60s tool-call cap (105s
# cold): every foreground Roll Call "timed out", reading as a hung/broken
# stack while the script was actually fine — it kept running and exited
# WARN. Checks accrete (three commits on 2026-08-20 alone), so runtime
# creep is a recurring drift mode and nothing else watches it. Threshold
# 50s: post-parallelization full runs measure 26-28s warm, so a warn here
# means real creep, not noise. Placed BEFORE the payload build so it
# lands in the yellow tally, the Hub POST, and the verdict. $SECONDS is
# bash's seconds-since-start builtin; the payload/POST/reminders tail adds
# a few seconds after this point, hence warning 10s shy of the cap.
if [ "${SECONDS:-0}" -ge 50 ]; then
  warn "preflight took ${SECONDS}s at the watchdog — creeping toward the ~60s Cowork tool-call cap (foreground Roll Call 'timeouts' return if this grows)" \
       "FIRST check host load (uptime — the watchdog's first live firing was load ~21 from browser/compositing, not check-creep, 2026-08-21); if load is normal, profile with per-line timestamps, find the new slow check, parallelize or background it (pattern: 2026-08-21 dedupe-sweep fix, wiki/log.md)"
fi

# ── Stack health payload → ~/.cache/ + Hub POST ─────────
# Always builds the payload (the Hub's /today card depends on it). JSON file
# only written when --json-out is passed. POST only happens if the shared
# Keychain secret lsh-stack-health-token is present; silent skip otherwise.
finalize_tool

if [ ${#TOOL_STATES[@]} -gt 0 ]; then
  STACK_PAYLOAD=$(python3 -c '
import sys, json
tools = [json.loads(a) for a in sys.argv[1:-1]]
reported_by = sys.argv[-1]
verdict = "ready"
if any(t["status"] == "danger" for t in tools): verdict = "block"
elif any(t["status"] == "warn" for t in tools): verdict = "warn"
print(json.dumps({"verdict": verdict, "tools": tools, "reported_by": reported_by}))
' "${TOOL_STATES[@]}" "$(whoami)@$(hostname -s 2>/dev/null || echo unknown)")   # unbound-ok: enclosed by [ ${#TOOL_STATES[@]} -gt 0 ] at 1625

  if [ -n "$JSON_OUT" ]; then
    mkdir -p "$(dirname "$JSON_OUT")"
    printf '%s\n' "$STACK_PAYLOAD" > "$JSON_OUT"
  fi

  STACK_TOKEN=$(security find-generic-password -s lsh-stack-health-token -w 2>/dev/null || true)
  if [ -n "$STACK_TOKEN" ]; then
    HUB_URL="${LSH_HEALTH_URL:-https://limitless-stack-hub.vercel.app}/api/stack/health/report"
    # Best-effort POST. 5s timeout. Network failures / 503s must not affect
    # the Roll Call verdict — preflight is the source of truth, the Hub is
    # a downstream consumer.
    curl -sS --max-time 5 \
      -H "Authorization: Bearer $STACK_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$STACK_PAYLOAD" \
      "$HUB_URL" > /dev/null 2>&1 || true
  fi

  # Also report this preflight run as an activity row (canary producer for the
  # /api/agent-activity endpoint). Shares the same Keychain token as the stack
  # health POST above; same best-effort semantics — failures must not affect
  # the Roll Call verdict. See tools/report-activity.sh for details.
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -x "$SCRIPT_DIR/report-activity.sh" ]; then
    if [ "$RED" -gt 0 ]; then
      ACT_VERDICT="block"
      ACT_TITLE="preflight BLOCK — $RED blocker(s)"
    elif [ "$YELLOW" -gt 0 ]; then
      ACT_VERDICT="warn"
      ACT_TITLE="preflight WARN — $YELLOW drift finding(s)"
    else
      ACT_VERDICT="ready"
      ACT_TITLE="preflight READY — $GREEN green"
    fi
    ACT_PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({
  "verdict": sys.argv[1],
  "green":   int(sys.argv[2]),
  "yellow":  int(sys.argv[3]),
  "red":     int(sys.argv[4]),
  "warnings": [w for w in sys.argv[5].split("\x1f") if w],
  "blockers": [b for b in sys.argv[6].split("\x1f") if b],
  "reported_by": sys.argv[7],
}))
' "$ACT_VERDICT" "$GREEN" "$YELLOW" "$RED" \
   "$(IFS=$'\x1f'; echo "${WARNINGS[*]:-}")" \
   "$(IFS=$'\x1f'; echo "${BLOCKERS[*]:-}")" \
   "$(whoami)@$(hostname -s 2>/dev/null || echo unknown)")
    "$SCRIPT_DIR/report-activity.sh" \
      --source     agent \
      --event-type preflight \
      --actor      roll-call \
      --repo       openscaffold-wiki \
      --title      "$ACT_TITLE" \
      --payload    "$ACT_PAYLOAD" || true
  fi
fi

# ── Per-user capability snapshot ────────────────────────
# Run scan-capabilities.py best-effort so every Roll Call refreshes the
# CURRENT MAC'S snapshot in the Hub. Each user gets tagged with their own
# GitHub login (via gh CLI inside scan-capabilities.py), so Dale's Hub view
# starts showing HIS plugin set the moment he greets Claude and Roll Call
# fires — no manual setup on his side. Failure here can't affect the
# Roll Call verdict — same best-effort contract as the activity POST above.
SCANNER="$SCRIPT_DIR/scan-capabilities.py"
if [ -x "$SCANNER" ] || [ -r "$SCANNER" ]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python3.11 "$SCANNER" > /dev/null 2>&1 || true
  elif command -v python3 >/dev/null 2>&1; then
    python3 "$SCANNER" > /dev/null 2>&1 || true
  fi
fi

# ── USAGE REMINDERS ─────────────────────────────────────
# Printed on every preflight run — binds each tool to the skill / routing
# pattern that uses it correctly, so the rules travel with the output.
# Self-improvement: if I catch myself drifting from a pattern mid-session,
# add a new line here before closing the session.
echo "───────────────────────────────────────────────────────"
echo "  USAGE REMINDERS — how to actually use each tool this session"
echo "───────────────────────────────────────────────────────"
echo ""
echo "  • Obsidian wiki  → Read/Edit via sandbox path (/sessions/.../mnt/obsidian /...)."
echo "                      Answer order: wiki/index.md → pages → Pinecone → NotebookLM."
echo "                      For substantive claims, invoke Skill(four-tool-lookup)."
echo ""
echo "  • Pinecone       → python3.11 tools/pinecone-search.py \"...\" via desktop-commander."
echo "                      Do NOT import pinecone-py in sandbox — API key lives in Mac Keychain."
echo ""
echo "  • NotebookLM     → Invoke Skill(notebooklm) for ANY NotebookLM operation."
echo "                      CLI always via mcp__desktop-commander__start_process("
echo "                        command=\"notebooklm use <id> && notebooklm ask '...'\","
echo "                        shell=\"zsh\", timeout_ms=90000)"
echo "                      Do NOT pip-install notebooklm-py or run notebooklm login in sandbox"
echo "                      (no display, wiped each session) — anti-pattern #10."
echo "                      Reminder layer: ab4b7ccb  ·  Full wiki mirror: cdaa7a43"
echo ""
echo "  • CLAUDE.md      → Read at session start; it's the trust anchor for all the above."
echo "                      Edit via the Edit tool on the sandbox path, commit + push at end."
echo ""
echo "  • End-of-session → (1) git commit + push vault · (2) pinecone-sync.py --changed-only"
echo "                      (3) notebooklm-wiki-refresh.py if wiki changed"
echo "                      (4) refresh ab4b7ccb sources if its curated files changed"
echo ""

# ── Machine-readable findings channel (--findings-out) ──
# Written here, where the counts + WARNINGS[]/BLOCKERS[] arrays are final. This
# is the STABLE contract for programmatic consumers (the Loop 5 nightly) so they
# never scrape the human-readable "  - msg  →  fix" lines. Each warning/blocker
# is the same "msg  →  fix" string the console prints, so a consumer gets an
# identical findings list without depending on console formatting.
# Re-probe BEFORE committing a verdict. The 2026-07-27 drop happened MID-RUN —
# pass 1 completed clean and the network died before pass 2 — so an up-front
# check alone would still let a run that started healthy and ended offline
# publish its manufactured failures. If the network went away while we were
# working, this run is indeterminate no matter what the counters say.
if ! network_probe; then network_abort "mid-run, before verdict"; fi

if [ -n "$FINDINGS_OUT" ]; then
  if   [ "$RED" -gt 0 ];    then FVERDICT="block"
  elif [ "$YELLOW" -gt 0 ]; then FVERDICT="warn"
  else                           FVERDICT="ready"; fi
  FINDINGS_JSON=$(python3 -c '
import sys, json, datetime
verdict, g, y, r = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
warnings = [w for w in sys.argv[5].split("\x1f") if w]
blockers = [b for b in sys.argv[6].split("\x1f") if b]
# accepted rides its OWN key, never inside warnings — a consumer that treats this
# list as drift would recreate exactly the padding this change removes. Carried in
# the machine channel anyway so the JSON does not silently know less than the
# console: a state the human can see and the nightly cannot is how a permanent
# blocker goes quiet. (2026-08-20)
accepted = [a for a in (sys.argv[7] if len(sys.argv) > 7 else "").split("\x1f") if a]
print(json.dumps({
  "verdict": verdict, "green": g, "yellow": y, "red": r,
  "accepted": len(accepted),
  "warnings": warnings, "blockers": blockers,
  "accepted_notes": accepted,
  "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}))
' "$FVERDICT" "$GREEN" "$YELLOW" "$RED" \
   "$(IFS=$'\x1f'; echo "${WARNINGS[*]:-}")" \
   "$(IFS=$'\x1f'; echo "${BLOCKERS[*]:-}")" \
   "$(IFS=$'\x1f'; echo "${ACCEPTED_NOTES[*]:-}")" 2>/dev/null)
  if [ -n "$FINDINGS_JSON" ]; then
    mkdir -p "$(dirname "$FINDINGS_OUT")" 2>/dev/null
    printf '%s\n' "$FINDINGS_JSON" > "$FINDINGS_OUT"
  fi
fi

# ── Verdict ─────────────────────────────────────────────
echo "───────────────────────────────────────────────────────"
# ⚠ The "green: N   yellow: N   red: N" substring is SCRAPED by nightly-selfheal.sh
# (grep -oE 'green: [0-9]+   yellow: [0-9]+   red: [0-9]+'). Anything new must be
# APPENDED after it — never inserted into it, or the nightly silently falls back to
# a different source for its counts.
if [ "$ACCEPTED" -gt 0 ]; then
  echo "  green: $GREEN   yellow: $YELLOW   red: $RED   accepted: $ACCEPTED"
else
  echo "  green: $GREEN   yellow: $YELLOW   red: $RED"
fi
echo ""

# Legitimate terminal state: everything below produces a REAL verdict, so flip
# the flag ONCE here rather than in each of the three branches.
PREFLIGHT_COMPLETED=true

if [ "$RED" -gt 0 ]; then
  echo "  ✗ VERDICT: BLOCK — do NOT start work"
  echo ""
  echo "  Blockers (fix first):"
  for b in "${BLOCKERS[@]}"; do echo "    - $b"; done   # unbound-ok: RED>0 branch, and bad() appends to BLOCKERS
  if [ "$YELLOW" -gt 0 ]; then
    echo ""
    echo "  Warnings:"
    for w in "${WARNINGS[@]}"; do echo "    - $w"; done   # unbound-ok: YELLOW>0 branch, and warn() appends to WARNINGS
  fi
  echo ""
  echo "  Before resuming work: fix blockers above, follow the USAGE REMINDERS."
  echo "═══════════════════════════════════════════════════════"
  exit 2
elif [ "$YELLOW" -gt 0 ]; then
  echo "  ⚠ VERDICT: WARN — $YELLOW drift finding(s)"
  echo ""
  echo "  Warnings (report to Matt, may proceed with acknowledgement):"
  for w in "${WARNINGS[@]}"; do echo "    - $w"; done   # unbound-ok: YELLOW>0 branch, and warn() appends to WARNINGS
  if [ "$ACCEPTED" -gt 0 ]; then
    echo ""
    echo "  Known-accepted state ($ACCEPTED — listed separately so it never pads the count above):"
    for a in "${ACCEPTED_NOTES[@]}"; do echo "    ℹ $a"; done   # unbound-ok: ACCEPTED>0 branch, accepted() appends to ACCEPTED_NOTES
  fi
  echo ""
  echo "  Proceed with the USAGE REMINDERS above as your routing contract."
  echo "═══════════════════════════════════════════════════════"
  exit 1
else
  echo "  ✓ VERDICT: READY — all limitless-stack tools green. Proceed."
  # READY does NOT mean "nothing is wrong anywhere" — it means nothing here is
  # drift a session can act on. Accepted state is still printed at READY on
  # purpose: silence would let a permanent blocker (the Pinecone cap) fade out of
  # every session's view, and a session that forgets the corpus is stale will
  # report an empty search as "no hits" instead of "not searched".
  if [ "$ACCEPTED" -gt 0 ]; then
    echo ""
    echo "  Known-accepted state ($ACCEPTED — real, but not this session's to clear):"
    for a in "${ACCEPTED_NOTES[@]}"; do echo "    ℹ $a"; done   # unbound-ok: ACCEPTED>0 branch, accepted() appends to ACCEPTED_NOTES
  fi
  echo "  Follow the USAGE REMINDERS above for every tool interaction this session."
  echo "═══════════════════════════════════════════════════════"
  exit 0
fi
