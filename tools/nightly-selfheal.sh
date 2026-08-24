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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derived from SCRIPT_DIR (tools/ sits directly under the vault), not hardcoded.
# An absolute Mac path pins a tool to one machine and makes it degrade to
# "I can't check that here" anywhere else — the class swept out of the toolchain
# 2026-08-24 and now blocked at commit by tools/path-portability-check.py.
# Order matters: SCRIPT_DIR must be assigned BEFORE this line.
VAULT="$(cd "$SCRIPT_DIR/.." && pwd)"
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
  local out rc fjson parsed counts s_green s_yellow s_red
  # Ask the preflight for its STABLE machine-readable findings channel (added
  # 2026-07-23 to kill the glyph/spacing-coupling SPOF both audits flagged).
  fjson="$LOG_DIR/.preflight-findings.$$.json"
  rm -f "$fjson"
  out="$(bash "$PREFLIGHT" --findings-out="$fjson" 2>&1)"; rc=$?
  PF_OUT="$out"; PF_RC=$rc

  # ALWAYS also scrape the console counts — used to CROSS-CHECK the JSON so a
  # valid-but-wrong JSON can't silently yield a false green (2026-07-23 audit).
  counts="$(printf '%s\n' "$out" | grep -oE 'green: [0-9]+   yellow: [0-9]+   red: [0-9]+' | tail -1)"
  s_green="$(printf '%s' "$counts" | grep -oE 'green: [0-9]+'  | grep -oE '[0-9]+')"
  s_yellow="$(printf '%s' "$counts" | grep -oE 'yellow: [0-9]+' | grep -oE '[0-9]+')"
  s_red="$(printf '%s' "$counts" | grep -oE 'red: [0-9]+'    | grep -oE '[0-9]+')"

  # PREFER the JSON: first line "green yellow red", then one finding per line
  # (blockers first, then warnings). Each finding is COLLAPSED to a single line
  # — some preflight fix hints are multi-line (e.g. a coverage-check traceback),
  # and every downstream consumer (plan_correctors, ACCEPTED_RE, the state file)
  # treats a finding as one line, exactly as the scrape path does. Not collapsing
  # would fragment one finding into several (2026-07-23 audit, HIGH).
  parsed=""
  if [ -s "$fjson" ]; then
    parsed="$(python3 - "$fjson" 2>/dev/null <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("%d %d %d" % (d.get("green", 0), d.get("yellow", 0), d.get("red", 0)))
for x in d.get("blockers", []) + d.get("warnings", []):
    print(" ".join(x.split()))   # collapse embedded newlines/tabs → one line
PY
)"
  fi

  if [ -n "$parsed" ]; then
    read -r PF_GREEN PF_YELLOW PF_RED <<< "$(printf '%s\n' "$parsed" | sed -n '1p')"
    PF_FINDINGS="$(printf '%s\n' "$parsed" | sed '1d')"
    PF_SOURCE="json"
    # Cross-check: if the console counts ARE present and DISAGREE with the JSON,
    # the JSON emit is buggy — distrust it and fall through to the scrape. (If
    # the console counts are ABSENT, the console format changed — which is
    # exactly what the JSON channel exists to survive — so keep the JSON.)
    if [ -n "$s_green$s_yellow$s_red" ] && \
       { [ "$PF_GREEN" != "$s_green" ] || [ "$PF_YELLOW" != "$s_yellow" ] || [ "$PF_RED" != "$s_red" ]; }; then
      log "  ⚠ findings JSON disagrees with console counts (json ${PF_GREEN}/${PF_YELLOW}/${PF_RED} vs scrape ${s_green}/${s_yellow}/${s_red}) — using scrape"
      parsed=""
    fi
  fi

  if [ -z "$parsed" ]; then
    # FALLBACK: scrape the human-readable console output (pre-hardening path).
    # Every warn()/bad() finding prints as "    - <msg>  →  <fix>"; the → filter
    # excludes other 4-space-indented bullets (e.g. the anti-patterns reminder).
    PF_FINDINGS="$(printf '%s\n' "$out" | grep '^    - ' | grep -F '→' | sed 's/^    - //')"
    PF_GREEN="$s_green"; PF_YELLOW="$s_yellow"; PF_RED="$s_red"
    PF_SOURCE="scrape"
  fi
  PF_GREEN="${PF_GREEN:-0}"; PF_YELLOW="${PF_YELLOW:-0}"; PF_RED="${PF_RED:-0}"

  # ── Shell-diagnostic detection (2026-08-24) ───────────
  # The SUBSHELL shape of the `set -u` class — dd10778, 2026-05-18 — dies inside
  # $( ), so the parent completes normally and EXITS 0. The preflight's own
  # completion assertion cannot see it (the flag legitimately flips true), and
  # tools/shell-unbound-check.py only guards what gets COMMITTED. The one
  # remaining tell is the diagnostic bash writes to stderr, which this function
  # already captures via 2>&1. So detect it here — the only fully-automatic
  # catcher of that shape, with no human in the loop.
  # NOT a second evaluator of "did it run": the completion flag answers that.
  # This answers a different question — "did the shell report an error at all".
  PF_DIAG="$(printf '%s\n' "$out" \
    | grep -oE '[A-Za-z0-9_.-]+\.sh: line [0-9]+: .*' | head -1 || true)"
  rm -f "$fjson"
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
log "pass $PASS: verdict rc=$PF_RC (green=$PF_GREEN yellow=$PF_YELLOW red=$PF_RED src=$PF_SOURCE)"

# rc=3 (no network) short-circuits the loop: there is nothing to correct, and a
# corrector that needs the network would only fail and pollute the log. Retrying
# passes here is also how a single drop got amplified into three broken verdicts
# on 2026-07-27.
while [ "$PF_RC" -ne 0 ] && [ "$PF_RC" -ne 3 ] && [ "$PASS" -lt "$MAX_PASSES" ]; do
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
  log "pass $PASS: verdict rc=$PF_RC (green=$PF_GREEN yellow=$PF_YELLOW red=$PF_RED src=$PF_SOURCE)"
done

# ── Outcome ─────────────────────────────────────────────
# FLOOR — an UNMEASURED run must never wear a ready title (added 2026-08-24).
# rc=1 means WARN, which means yellow>0; so 0/0/0 counts alongside rc=1 is a
# CONTRADICTION — it means no count was READABLE, not that nothing was wrong.
# Both channels have to have failed: the findings JSON absent AND the console
# scrape matching nothing. That is an instrument failure, and an instrument
# failure is actionable in a way a 4am DNS drop is not — so this escalates,
# unlike rc=3.
#   Live occurrence: 2026-08-24 04:12 logged
#   "rc=1 (green=0 yellow=0 red=0 src=scrape)" → "READY* — 0 residual (no action)"
#   having evaluated nothing, because the preflight had aborted at check 3/7.
#   That specific CAUSE is now closed upstream (the preflight exits 2 on abort,
#   and PF_DIAG catches its stderr) — but the CLASS is not: verified 2026-08-24
#   against this exact script with a stub preflight that exits 1, prints no
#   counts and emits no diagnostic. It still titled READY*, needs_human=false.
#   Keyed on the SUM, so a genuine warn with counts (e.g. 0 green/4 yellow) is
#   untouched — negative-controlled, that case still titles READY* correctly.
PF_UNMEASURED=""
if [ "$PF_RC" -eq 1 ] && [ "$((PF_GREEN + PF_YELLOW + PF_RED))" -eq 0 ]; then
  PF_UNMEASURED="preflight returned WARN but reported 0 green / 0 yellow / 0 red (src=${PF_SOURCE:-unknown}) — nothing was measurable"
  log "  ⚠ FLOOR: $PF_UNMEASURED"
fi

case "$PF_RC" in
  0) VERDICT="ready" ;;
  1) if [ -n "$PF_UNMEASURED" ]; then VERDICT="block"; else VERDICT="warn"; fi ;;
  # rc=3 — the preflight found no working network and evaluated NOTHING (added
  # 2026-07-27). This is not a verdict about the stack and must never become a
  # block: on 2026-07-27 a mid-run DNS drop produced red=2/yellow=12 that looked
  # like fourteen problems and was one, and the same checks were green three
  # hours later. Recorded and left alone — no correctors, no needs_human.
  3) VERDICT="indeterminate" ;;
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
#   • "last nightly self-heal ..." — the preflight's [meta] readout of the
#     nightly's OWN prior state, in ANY of its phrasings. Counting it as
#     actionable creates a LATCH: once a run ends needs_human=true, every later
#     run re-reads that warn as fresh drift and can never self-clear. Excluding
#     it lets a genuinely-clean night report clean. (The preflight still shows
#     it to a HUMAN at Roll Call.)
#     ⚠ 2026-08-22: this guard originally matched only the legacy phrasing
#     "last nightly self-heal ended". The preflight later grew three sibling
#     formats ("last nightly self-heal: N actionable…", the needs_human-
#     disagreement line, the STALE line) and the latch RETURNED through the
#     unmatched ones — double-nested messages in the state file proved it
#     (#34-shaped: the guard was not a strict superset of the message family).
#     Now matched on the stable prefix: every "last nightly self-heal" line is
#     self-referential BY CONSTRUCTION when the nightly itself is the reader.
# Matched by finding IDENTITY, not a loose keyword (the old 'quota' substring
# could suppress a real finding that merely contained the word). uncommitted +
# tightening added per the 2026-07-23 design audit; the self-referential latch
# was caught by running the nightly twice that same day.
ACCEPTED_RE='Pinecone embedding quota exhausted|newer than last Pinecone sync|uncommitted files in vault|last nightly self-heal|anti-pattern review due'
RESIDUAL_ACTIONABLE=""
if [ "$PF_RC" -ne 0 ]; then
  RESIDUAL_ACTIONABLE="$(printf '%s\n' "$PF_FINDINGS" | grep -viE "$ACCEPTED_RE" | grep -v '^[[:space:]]*$' || true)"
fi
ACTIONABLE_N=$(printf '%s\n' "$RESIDUAL_ACTIONABLE" | grep -c . || echo 0)
NEEDS_HUMAN="false"
if [ "$VERDICT" = "block" ] || [ -n "$RESIDUAL_ACTIONABLE" ]; then NEEDS_HUMAN="true"; fi
# An indeterminate run evaluated nothing, so it has no findings to escalate and
# nothing a human could act on. Waking someone to tell them the laptop's wifi
# dropped at 4am is the cry-wolf failure this whole guard exists to remove.
if [ "$VERDICT" = "indeterminate" ]; then NEEDS_HUMAN="false"; RESIDUAL_ACTIONABLE=""; ACTIONABLE_N=0; fi

# A shell diagnostic escalates REGARDLESS of exit code, and deliberately sits
# AFTER the indeterminate reset. Reason: the block above only computes
# RESIDUAL_ACTIONABLE when rc != 0, but the subshell shape this catches exits
# ZERO — dd10778 exited 0 for two weeks while printing the error every run. A
# diagnostic is never normal, so unlike a 4am DNS drop it is always worth a
# human. Added 2026-08-24 (claude-anti-patterns #72).
if [ -n "${PF_DIAG:-}" ]; then
  RESIDUAL_ACTIONABLE="$(printf '%s\n%s' "$RESIDUAL_ACTIONABLE" \
    "preflight emitted a shell diagnostic — $PF_DIAG  →  python3.11 tools/shell-unbound-check.py && bash tools/test-preflight-abort.sh --full" \
    | grep -v '^[[:space:]]*$' || true)"
  ACTIONABLE_N=$(printf '%s\n' "$RESIDUAL_ACTIONABLE" | grep -c . || echo 0)
  NEEDS_HUMAN="true"
fi

# Same placement logic as PF_DIAG above, and for the same reason: this must sit
# AFTER the indeterminate reset so it cannot be cleared. An unmeasured run has
# no findings to escalate BY DEFINITION — the escalation IS "nothing could be
# read", which is exactly the state a silent needs_human=false would hide.
if [ -n "${PF_UNMEASURED:-}" ]; then
  RESIDUAL_ACTIONABLE="$(printf '%s\n%s' "$RESIDUAL_ACTIONABLE" \
    "$PF_UNMEASURED  →  run the preflight by hand and read its tail: env -u LIMITLESS_STACK_HOME bash tools/limitless-preflight.sh; tail -25" \
    | grep -v '^[[:space:]]*$' || true)"
  ACTIONABLE_N=$(printf '%s\n' "$RESIDUAL_ACTIONABLE" | grep -c . || echo 0)
  NEEDS_HUMAN="true"
fi

# Dedup corrector list.
UNIQ_CORR="$(printf '%s\n' "${CORRECTORS_RUN[@]:-}" | sort -u | grep -v '^$' | paste -sd, - 2>/dev/null)"

# Build a title for the activity heartbeat / escalation row.
# Indeterminate FIRST — before the needs_human=false branch below, which would
# otherwise title a run that evaluated nothing as "READY*". Reporting ready when
# no check ran is the inverse of the cry-wolf failure and is worse: a false green
# is believed, a false red is eventually investigated.
if [ "$VERDICT" = "indeterminate" ]; then
  TITLE="nightly self-heal: INDETERMINATE — no network, nothing evaluated (no action)"
elif [ -n "${PF_UNMEASURED:-}" ]; then
  # Must outrank every ready branch for the same reason INDETERMINATE does: a run
  # that measured nothing has no business carrying a ready headline. Distinct
  # from INDETERMINATE because that one is a known-benign cause (no network) and
  # deliberately does not wake anyone; this one means the INSTRUMENT failed.
  TITLE="nightly self-heal: UNMEASURED — preflight said WARN but reported no counts (needs human)"
elif [ -n "${PF_DIAG:-}" ]; then
  # Must outrank the "ready" branches below. The subshell shape exits 0 with a
  # clean verdict, so without this the headline reads "READY (31 green)" while
  # needs_human is quietly true — a false green with an alarm nobody sees.
  # Verified against a fake preflight reproducing exactly that shape.
  TITLE="nightly self-heal: SHELL DIAGNOSTIC — $PF_DIAG (needs human)"
elif [ "$VERDICT" = "ready" ] && [ "$HEALED" = "true" ]; then
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
# actionable is appended LAST so every existing argv index is undisturbed.
# It is published because THIS script is the only place that classifies a finding
# as actionable (ACCEPTED_RE above). The preflight used to read residual_findings
# — which holds ALL of them — and report the raw count, so one real finding got
# announced as five with the real one buried. Publishing the classifier's own
# answer keeps a single evaluator instead of making the preflight re-derive it.
# (2026-08-20)
STATE_JSON="$(python3 - "$VERDICT" "$PF_GREEN" "$PF_YELLOW" "$PF_RED" "$PASS" \
                         "$HEALED" "$HOST" "${UNIQ_CORR:-}" "$PF_FINDINGS" "$NEEDS_HUMAN" \
                         "${RESIDUAL_ACTIONABLE:-}" <<'PY'
import json, sys, datetime
verdict, green, yellow, red, passes, healed, host, corr, findings, needs_human = sys.argv[1:11]
actionable = sys.argv[11] if len(sys.argv) > 11 else ""
actionable_list = [l for l in actionable.splitlines() if l.strip()]
print(json.dumps({
  "actionable_findings": actionable_list,
  "actionable_n":        len(actionable_list),
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
