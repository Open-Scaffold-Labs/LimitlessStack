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

# ── Single-instance lock ────────────────────────────────
# A manual `launchctl kickstart` can collide with the 04:10 scheduled fire (and
# repeated kickstarts stack up) — concurrent runs waste the NotebookLM sweep and
# race on the state file. mkdir is atomic → a clean lock; a lock whose pid is
# dead is reclaimed as stale. (2026-07-23 audit — observed real overlap.)
LOCK_DIR="$SCRIPT_DIR/.nightly-selfheal.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [ -f "$LOCK_DIR/pid" ] && kill -0 "$(cat "$LOCK_DIR/pid" 2>/dev/null)" 2>/dev/null; then
    log "another nightly-selfheal run is active (pid $(cat "$LOCK_DIR/pid")) — exiting"
    exit 0
  fi
  rm -rf "$LOCK_DIR"                        # stale lock (dead pid) — reclaim
  mkdir "$LOCK_DIR" 2>/dev/null || { log "lock race — exiting"; exit 0; }
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

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
# human or is a known-accepted state.
#
# EXCLUSION (2026-07-23 design audit): `--only reminder` is NOT auto-run — for
# file sources `--force` is a no-op (CLAUDE.md step 7) so it cannot actually
# heal (it would log success, leave the finding, burn budget, escalate anyway),
# and unattended mutation of the curated reminder layer is out of "safe
# corrector" scope. Reminder drift is left to a human.
#
# Emits one corrector per line as TAB-separated `tool<TAB>label<TAB>flags`
# (label/flags empty for pinecone). The caller dispatches with an explicit args
# array — NO eval, no command-string reconstruction. Labels are [a-z0-9-]+.
plan_correctors() {
  local findings="$1"
  local quota_present=0
  printf '%s\n' "$findings" | grep -qi 'quota' && quota_present=1
  printf '%s\n' "$findings" | while IFS= read -r line; do
    [ -z "$line" ] && continue
    local fix="${line#*→}"    # text after the arrow = the preflight's fix hint
    case "$fix" in
      *notebooklm-wiki-refresh.py*--only*)
        local label flags=""
        label="$(printf '%s' "$fix" | sed -nE 's/.*--only[[:space:]]+([a-z0-9-]+).*/\1/p')"
        [ "$label" = "reminder" ] && continue   # not auto-healable (see header)
        printf '%s' "$fix" | grep -q -- '--seed'            && flags="$flags --seed"
        printf '%s' "$fix" | grep -q -- '--force'           && flags="$flags --force"
        printf '%s' "$fix" | grep -q -- '--verify-existing' && flags="$flags --verify-existing"
        [ -n "$label" ] && printf 'notebooklm\t%s\t%s\n' "$label" "${flags# }"
        ;;
      *pinecone-sync.py*--changed-only*)
        [ "$quota_present" -eq 0 ] && printf 'pinecone\t\t\n'
        ;;
    esac
  done | sort -u
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
  while IFS=$'\t' read -r tool label flags; do
    [ -z "$tool" ] && continue
    case "$tool" in
      notebooklm)
        log "  ↻ corrector: notebooklm-wiki-refresh.py${flags:+ $flags} --only $label"
        # $flags is a fixed whitelist of our own flags — intentional word-split.
        # shellcheck disable=SC2086
        if python3.11 "$SCRIPT_DIR/notebooklm-wiki-refresh.py" $flags --only "$label" >>"$LOG_FILE" 2>&1
          then log "    ✓ done"; else log "    ✗ exited non-zero (see log)"; fi
        CORRECTORS_RUN+=("notebooklm:$label") ;;
      pinecone)
        log "  ↻ corrector: pinecone-sync.py --changed-only"
        if python3.11 "$SCRIPT_DIR/pinecone-sync.py" --changed-only >>"$LOG_FILE" 2>&1
          then log "    ✓ done"; else log "    ✗ exited non-zero (see log)"; fi
        CORRECTORS_RUN+=("pinecone") ;;
    esac
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

# Report-only / non-escalating residual states — recorded in the state file but
# they do NOT set needs_human, so the nightly never cries wolf on them:
#   • "Pinecone embedding quota exhausted" + its downstream sync-lag — unfixable
#     by any corrector until the monthly cap resets.
#   • "uncommitted files in vault" — human-gated by policy (the nightly must
#     NEVER commit), so escalating it every morning is pure noise.
#   • "last nightly self-heal ended ..." — the preflight's [meta] readout of the
#     nightly's OWN prior state. Counting it as actionable creates a LATCH: once
#     a run ends needs_human=true, every later run re-reads that warn as fresh
#     drift and can never self-clear. Excluding it lets a genuinely-clean night
#     report clean. (The preflight still shows it to a HUMAN at Roll Call.)
# Matched by finding IDENTITY, not a loose keyword (the old 'quota' substring
# could suppress a real finding that merely contained the word). uncommitted +
# tightening added per the 2026-07-23 design audit; the self-referential latch
# was caught by running the nightly twice that same day.
ACCEPTED_RE='Pinecone embedding quota exhausted|newer than last Pinecone sync|uncommitted files in vault|last nightly self-heal ended'
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
# Atomic write (temp + mv) so a concurrent preflight read never sees a
# half-written file. (2026-07-23 audit.)
printf '%s\n' "$STATE_JSON" > "$STATE_FILE.tmp" && mv -f "$STATE_FILE.tmp" "$STATE_FILE"
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
