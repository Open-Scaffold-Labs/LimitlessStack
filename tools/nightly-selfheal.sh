#!/usr/bin/env bash
# nightly-selfheal.sh — the Limitless Stack's scheduled OUTER loop (Loop 5).
#
# Runs unattended each night (launchd: com.openscaffold.nightly-selfheal).
# Shape follows loop-engineering-for-the-stack.md rec #4:
#
#   run preflight  →  grade (its verdict)  →  auto-run ONLY deterministic
#   correctors  →  re-verify  →  (budget 3 passes)  →  record + escalate.
#
# DESIGN CONTRACT (do not weaken without Matt's sign-off):
#   • Self-heals ONLY the two deterministic, idempotent, reversible correctors:
#       - notebooklm-wiki-refresh.py   (NotebookLM mirror drift; has heal_verify)
#       - pinecone-sync.py --changed-only   (skipped when the quota-exhausted
#         finding is present — running it then just fails)
#   • NEVER commits, pushes, force-anything, or edits CLAUDE.md / wiki content.
#     git / uncommitted-file findings are REPORTED, never auto-resolved —
#     those stay human-gated per CLAUDE.md "always ask Matt before acting".
#   • Auth-failure (BLOCK) findings are NOT auto-fixed — escalated to a human.
#   • Budget: at most 3 preflight passes (initial + 2 fix/recheck). Cannot loop
#     forever. Correctors run at most twice.
#
# OUTPUT:
#   • tools/.nightly-selfheal-state.json   — machine-readable run record the
#     NEXT preflight reads to surface "last nightly: PASS/HEALED/FAIL".
#   • tools/logs/nightly-selfheal-YYYYMMDD.log — full transcript.
#   • one Hub activity row per run (heartbeat + escalation) via report-activity.sh.
#
# Exit code mirrors the FINAL preflight verdict (0 ready / 1 warn / 2 block),
# but launchd ignores it; the state file + activity row are the real signal.

set -u

# Robust PATH — launchd agents start with a minimal PATH; python3.11, notebooklm,
# git, curl all live in /opt/homebrew/bin or /usr/bin.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

VAULT="/Users/matthewlavin/Claude code antigravity/obsidian "
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFLIGHT="$SCRIPT_DIR/limitless-preflight.sh"
STATE_FILE="$SCRIPT_DIR/.nightly-selfheal-state.json"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nightly-selfheal-$(date +%Y%m%d).log"

MAX_PASSES=3          # hard budget — cannot exceed this many preflight runs
HOST="$(whoami)@$(hostname -s 2>/dev/null || echo unknown)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG_FILE"; }

cd "$VAULT" || { log "FATAL: cannot cd to vault"; exit 2; }

log "──────── nightly self-heal starting (host=$HOST) ────────"

# Run the preflight once; capture stdout+stderr and its exit code.
# Echoes: OUT (captured transcript) and RC (0/1/2).
run_preflight() {
  local out rc
  out="$(bash "$PREFLIGHT" 2>&1)"; rc=$?
  PF_OUT="$out"; PF_RC=$rc
  # Extract ONLY verdict-block findings. Every warn()/bad() finding is printed
  # as "    - <msg>  →  <fix>" (guaranteed to contain the → separator), which
  # cleanly excludes other 4-space-indented bullet lists in the preflight output
  # (e.g. the anti-patterns reminder). Keep the "msg  →  fix" shape intact so
  # the corrector planner can read the scoped fix hint the preflight emitted.
  PF_FINDINGS="$(printf '%s\n' "$out" | grep '^    - ' | grep -F '→' | sed 's/^    - //')"
  # Counts from the "green: N   yellow: N   red: N" summary line.
  local counts
  counts="$(printf '%s\n' "$out" | grep -oE 'green: [0-9]+   yellow: [0-9]+   red: [0-9]+' | tail -1)"
  PF_GREEN="$(printf '%s' "$counts" | grep -oE 'green: [0-9]+'  | grep -oE '[0-9]+')"
  PF_YELLOW="$(printf '%s' "$counts" | grep -oE 'yellow: [0-9]+' | grep -oE '[0-9]+')"
  PF_RED="$(printf '%s' "$counts" | grep -oE 'red: [0-9]+'    | grep -oE '[0-9]+')"
  PF_GREEN="${PF_GREEN:-0}"; PF_YELLOW="${PF_YELLOW:-0}"; PF_RED="${PF_RED:-0}"
}

# Build the list of SAFE, SCOPED corrector commands to run — taken from the fix
# hint the preflight ITSELF emitted (the text after "  →  "). We only auto-run
# two whitelisted, deterministic, idempotent tools, and we run them EXACTLY as
# the preflight scoped them (e.g. `--only wiki`) so we never do a slow unscoped
# all-routes refresh (that unscoped run is anti-pattern #19). Everything else —
# git/commit, launchd install, canonical drift, Pinecone quota — is left for a
# human or is a known-accepted state. Reconstructs the command from a fixed
# template + the extracted flags (never eval's the raw hint) so a malformed hint
# can't inject anything: the route label is constrained to [a-z-]+.
# Prints one shell command per line (deduped).
plan_correctors() {
  local findings="$1"
  local quota_present=0
  printf '%s\n' "$findings" | grep -qi 'quota' && quota_present=1
  printf '%s\n' "$findings" | while IFS= read -r line; do
    [ -z "$line" ] && continue
    local fix="${line#*→}"    # text after the arrow = the preflight's fix hint
    case "$fix" in
      *notebooklm-wiki-refresh.py*--only*)
        local label force="" verify="" seed=""
        label="$(printf '%s' "$fix" | sed -nE 's/.*--only[[:space:]]+([a-z-]+).*/\1/p')"
        printf '%s' "$fix" | grep -q -- '--force'           && force=" --force"
        printf '%s' "$fix" | grep -q -- '--verify-existing' && verify=" --verify-existing"
        printf '%s' "$fix" | grep -q -- '--seed'            && seed=" --seed"
        [ -n "$label" ] && echo "python3.11 \"$SCRIPT_DIR/notebooklm-wiki-refresh.py\"$seed$force$verify --only $label"
        ;;
      *pinecone-sync.py*--changed-only*)
        [ "$quota_present" -eq 0 ] && echo "python3.11 \"$SCRIPT_DIR/pinecone-sync.py\" --changed-only"
        ;;
    esac
  done | sort -u
}

# Short state-file tag for a corrector command (e.g. "notebooklm:wiki", "pinecone").
corrector_tag() {
  case "$1" in
    *notebooklm-wiki-refresh*) echo "notebooklm:$(printf '%s' "$1" | sed -nE 's/.*--only ([a-z-]+).*/\1/p')" ;;
    *pinecone-sync*)           echo "pinecone" ;;
    *)                         echo "unknown" ;;
  esac
}

# ── The loop ────────────────────────────────────────────
CORRECTORS_RUN=()
PASS=0
run_preflight
PASS=$((PASS+1))
START_RC=$PF_RC
log "pass $PASS: verdict rc=$PF_RC (green=$PF_GREEN yellow=$PF_YELLOW red=$PF_RED)"

while [ "$PF_RC" -ne 0 ] && [ "$PASS" -lt "$MAX_PASSES" ]; do
  PLAN="$(plan_correctors "$PF_FINDINGS")"
  if [ -z "$PLAN" ]; then
    log "  no deterministic corrector applies to residual findings — stopping (human-gated)"
    break
  fi
  while IFS= read -r cmd; do
    [ -z "$cmd" ] && continue
    log "  ↻ corrector: $cmd"
    if eval "$cmd" >>"$LOG_FILE" 2>&1; then log "    ✓ done"; else log "    ✗ exited non-zero (see log)"; fi
    CORRECTORS_RUN+=("$(corrector_tag "$cmd")")
  done <<< "$PLAN"
  run_preflight
  PASS=$((PASS+1))
  log "pass $PASS: verdict rc=$PF_RC (green=$PF_GREEN yellow=$PF_YELLOW red=$PF_RED)"
done

# ── Outcome ─────────────────────────────────────────────
case "$PF_RC" in
  0) VERDICT="ready" ;;
  1) VERDICT="warn"  ;;
  *) VERDICT="block" ;;
esac
HEALED="false"
if [ "$START_RC" -ne 0 ] && [ "$PF_RC" -eq 0 ]; then HEALED="true"; fi

# Known-accepted residual states — no corrector can (or should) fix them and
# they do NOT warrant waking a human. Currently: the Pinecone embedding
# monthly-quota exhaustion and its downstream "wiki newer than last Pinecone
# sync". Recorded in the state file, but excluded from the needs-human decision
# so the nightly doesn't nag every morning until the quota resets.
ACCEPTED_RE='quota|newer than last Pinecone sync'
RESIDUAL_ACTIONABLE=""
if [ "$PF_RC" -ne 0 ]; then
  RESIDUAL_ACTIONABLE="$(printf '%s\n' "$PF_FINDINGS" | grep -viE "$ACCEPTED_RE" | grep -v '^[[:space:]]*$' || true)"
fi
ACTIONABLE_N=$(printf '%s\n' "$RESIDUAL_ACTIONABLE" | grep -c . || echo 0)
NEEDS_HUMAN="false"
if [ "$VERDICT" = "block" ] || [ -n "$RESIDUAL_ACTIONABLE" ]; then NEEDS_HUMAN="true"; fi

# Dedup corrector list.
UNIQ_CORR="$(printf '%s\n' "${CORRECTORS_RUN[@]:-}" | sort -u | grep -v '^$' | paste -sd, - 2>/dev/null)"

# Build a title for the activity heartbeat / escalation row.
if [ "$VERDICT" = "ready" ] && [ "$HEALED" = "true" ]; then
  TITLE="nightly self-heal: HEALED → READY (${UNIQ_CORR:-none})"
elif [ "$VERDICT" = "ready" ]; then
  TITLE="nightly self-heal: READY (${PF_GREEN} green)"
elif [ "$NEEDS_HUMAN" = "false" ]; then
  TITLE="nightly self-heal: READY* — ${PF_YELLOW} known-accepted residual (no action)"
elif [ "$VERDICT" = "warn" ]; then
  TITLE="nightly self-heal: WARN — ${ACTIONABLE_N} actionable finding(s) (needs human)"
else
  TITLE="nightly self-heal: BLOCK — ${PF_RED} blocker(s) (needs human)"
fi
log "outcome: $TITLE  [passes=$PASS healed=$HEALED needs_human=$NEEDS_HUMAN correctors=${UNIQ_CORR:-none}]"

# ── State file (machine-readable, read by next preflight) ──
STATE_JSON="$(python3 - "$VERDICT" "$PF_GREEN" "$PF_YELLOW" "$PF_RED" "$PASS" \
                         "$HEALED" "$HOST" "${UNIQ_CORR:-}" "$PF_FINDINGS" "$NEEDS_HUMAN" <<'PY'
import json, sys, datetime
verdict, green, yellow, red, passes, healed, host, corr, findings, needs_human = sys.argv[1:11]
print(json.dumps({
  "last_run":        datetime.datetime.now(datetime.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"),
  "final_verdict":   verdict,
  "needs_human":     needs_human == "true",
  "green":  int(green), "yellow": int(yellow), "red": int(red),
  "passes": int(passes),
  "healed": healed == "true",
  "correctors_run":  [c for c in corr.split(",") if c],
  "residual_findings": [l for l in findings.splitlines() if l.strip()] if verdict != "ready" else [],
  "host": host,
}, indent=2))
PY
)"
printf '%s\n' "$STATE_JSON" > "$STATE_FILE"
log "wrote state → $STATE_FILE"

# ── Hub activity row (heartbeat every run; the row IS the escalation when
#    verdict != ready). Best-effort — never affects the run outcome. ──
if [ -x "$SCRIPT_DIR/report-activity.sh" ]; then
  "$SCRIPT_DIR/report-activity.sh" \
    --source     agent \
    --event-type nightly-selfheal \
    --actor      nightly-selfheal \
    --repo       openscaffold-wiki \
    --title      "$TITLE" \
    --payload    "$STATE_JSON" || true
fi

log "──────── nightly self-heal done (verdict=$VERDICT) ────────"
exit "$PF_RC"
