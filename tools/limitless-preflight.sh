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
#
# Self-improvement rule: if a drift mode is discovered during a session that
# this script didn't catch, add a new check here before closing the session.

set -u

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$VAULT" || { echo "ERROR: cannot cd to vault $VAULT"; exit 2; }

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
WARNINGS=()
BLOCKERS=()

# ── CLI args ────────────────────────────────────────────
# --json-out         → writes ~/.cache/limitless-stack/health.json with payload
# --json-out=PATH    → writes payload to an explicit path
JSON_OUT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --json-out)       JSON_OUT="${HOME}/.cache/limitless-stack/health.json" ;;
    --json-out=*)     JSON_OUT="${1#*=}" ;;
    -h|--help)
      echo "usage: limitless-preflight.sh [--json-out[=PATH]]"
      echo "  POST to the Hub happens automatically if Keychain has"
      echo "  lsh-stack-health-token (shared secret)."
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

banner() {
  echo "═══════════════════════════════════════════════════════"
  echo "  LIMITLESS STACK — ROLL CALL"
  echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "═══════════════════════════════════════════════════════"
}

banner
echo ""

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
echo ""

# ── Limitless Stack canonical sync ──────────────────────
# Hub vault's tools/ and ~/.claude/skills/ MUST match the LimitlessStack
# canonical at $LIMITLESS_STACK_HOME (default /Users/matthewlavin/LimitlessStack).
# Closes the failure mode where fixes accumulate in one place but never make it
# back to the other — observed 2026-04-29 when 174 lines of cmd_replace/
# routing/coverage fixes lived in the Hub vault for a session before the gap
# was caught. The contract is: any future drift here fails the next session's
# Roll Call, with a one-line cp command in the warning so it can't go unfixed.
echo "[meta] Limitless Stack canonical sync"
LIMITLESS_STACK_HOME="${LIMITLESS_STACK_HOME:-/Users/matthewlavin/LimitlessStack}"
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
      warn "tools/$fname drifted from LimitlessStack canonical" \
           "diff \"$VAULT/tools/$fname\" \"$LIMITLESS_STACK_HOME/tools/$fname\"  — then cp the newer one over the older"
    fi
  done
  if $tools_clean; then
    ok "tools/ in sync with LimitlessStack canonical ($LIMITLESS_STACK_HOME)"
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
      warn "skill '$s' drifted from LimitlessStack canonical" \
           "cp $LIMITLESS_STACK_HOME/skills/$s/SKILL.md ~/.claude/skills/$s/SKILL.md  (or rerun install.sh)"
    fi
  done
  if $skills_clean; then
    ok "skills in sync with LimitlessStack canonical"
  fi
else
  warn "LIMITLESS_STACK_HOME ($LIMITLESS_STACK_HOME) not present — can't verify Limitless Stack sync" \
       "git clone https://github.com/Open-Scaffold-Labs/LimitlessStack.git \$HOME/LimitlessStack  (or set LIMITLESS_STACK_HOME)"
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
    warn "Pinecone embedding quota exhausted (monthly cap hit) — accepting as known state, session may proceed" "pinecone-search + pinecone-sync are non-functional until monthly reset or embedding source is swapped (see wiki/concepts/pinecone-warehouse.md)"
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
        warn "wiki has edits newer than last Pinecone sync (wiki ${WIKI_AGE_HOURS}h old, last sync ${LAST_SYNC_AGE_HOURS}h ago)" "python3.11 tools/pinecone-sync.py --changed-only"
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
  AUTH_OUT=$(notebooklm auth check --test 2>&1)
  if echo "$AUTH_OUT" | grep -q "Authentication Check" && ! echo "$AUTH_OUT" | grep -q "fail"; then
    ok "auth OK (storage_state.json valid, token fetch works)"
  elif echo "$AUTH_OUT" | grep -q "fail"; then
    bad "NotebookLM auth failing" "invoke Skill(notebooklm), then notebooklm login — do NOT try in the sandbox"
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

  # Per-project notebook freshness — each routed file compared against its route's state file.
  # Routes come from the project manifest's NOTEBOOKLM.routes list. Empty routes
  # (the-match, simple verticals) → loop runs 0 iterations.
  # Backwards-compat: no manifest → use Hub-vault hardcoded list.
  if [ -n "$LIMITLESS_PROJECT_ROUTES" ] || [ -f "$VAULT/.limitless-project.py" ]; then
    _ROUTE_LIST="$LIMITLESS_PROJECT_ROUTES"
  else
    _ROUTE_LIST="firehazmat:wiki/apps/firehazmat.md openchiropractor:wiki/apps/openchiropractor.md openfirehouse:wiki/apps/openfirehouse.md opensalon:wiki/apps/opensalon.md the-match:wiki/apps/the-match.md"
  fi
  for route in $_ROUTE_LIST; do
    label="${route%%:*}"
    file="${route#*:}"
    state_path="$VAULT/tools/.notebooklm-${label}-state.json"
    target="$VAULT/$file"
    if [ ! -f "$state_path" ]; then
      warn "no notebooklm $label state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only $label"
      continue
    fi
    if [ ! -f "$target" ]; then
      # routed file missing on disk — other checks cover this
      continue
    fi
    STATE_TS=$(stat -f '%m' "$state_path" 2>/dev/null || echo 0)
    FILE_TS=$(stat -f '%m' "$target" 2>/dev/null || echo 0)
    AGE_HOURS=$(( (NOW_TS - STATE_TS) / 3600 ))
    if [ "$FILE_TS" -gt "$STATE_TS" ]; then
      warn "notebooklm $label mirror stale ($file edited since last refresh, ${AGE_HOURS}h ago)" "python3.11 tools/notebooklm-wiki-refresh.py --only $label"
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
  if ! $_HAS_HUB_ROUTE; then
    : # skip hub route check — project doesn't have one
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
      warn "notebooklm wiki default bucket (cdaa7a43) has edits newer than last refresh (${LAST_REFRESH_AGE_HOURS}h ago)" "python3.11 tools/notebooklm-wiki-refresh.py --only wiki"
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

    if [ "$AB_STALE" -gt 0 ] && [ "$AB_UNVERIFIED" -gt 0 ]; then
      bad "ab4b7ccb reminder notebook: $AB_STALE source(s) edited since last verify + $AB_UNVERIFIED never verified" "python3.11 tools/notebooklm-wiki-refresh.py --force --only reminder  (then --verify-existing)"
    elif [ "$AB_STALE" -gt 0 ]; then
      warn "ab4b7ccb reminder notebook: $AB_STALE source(s) edited since last verified upload" "python3.11 tools/notebooklm-wiki-refresh.py --force --only reminder"
    elif [ "$AB_UNVERIFIED" -gt 0 ]; then
      warn "ab4b7ccb reminder notebook: $AB_UNVERIFIED source(s) have no verified_at timestamp" "python3.11 tools/notebooklm-wiki-refresh.py --verify-existing --only reminder"
    else
      ok "ab4b7ccb reminder notebook sources content-verified"
    fi
  else
    warn "no reminder-notebook state file" "python3.11 tools/notebooklm-wiki-refresh.py --seed --only reminder"
  fi

  # Duplicate-source audit across ALL 7 notebooks — added 2026-04-26 PM
  # after the original single-cdaa7a43 check (which was reporting clean
  # for weeks while ab4b7ccb and ca083f4f were silently accumulating 13
  # duplicates between them — caught by an end-of-session manual sweep).
  # Each `notebooklm source list` call is ~1-2s, so 7 notebooks add ~10s
  # to the preflight. Worth it: this is the layer Claude reads at the
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
    for entry in $notebooks; do
      nb_id="${entry%%:*}"
      nb_label="${entry##*:}"
      DUPE_COUNT=$(notebooklm use "$nb_id" >/dev/null 2>&1 && \
                   notebooklm source list --json 2>/dev/null | \
                   python3.11 -c "
import json, sys
from collections import Counter
try:
    d = json.load(sys.stdin)
    s = d if isinstance(d, list) else d.get('sources', [])
    titles = [src.get('title') for src in s]
    print(sum(c - 1 for c in Counter(titles).values() if c > 1))
except Exception:
    print(-1)
" 2>/dev/null || echo -1)
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
        warn "notebooklm $nb_id ($nb_label) has $DUPE_COUNT duplicate source(s)" \
             "python3.11 tools/notebooklm-dedupe.py --notebook $nb_id --state $nb_label  (dry-run first, then --apply)"
        sweep_dirty="${sweep_dirty}${nb_id} "
      fi
    done
    if [ -z "$sweep_dirty" ] && [ "$sweep_skipped" -eq 0 ]; then
      ok "notebooklm dedupe sweep: 0 duplicates across 8 notebooks"
    elif [ -z "$sweep_dirty" ] && [ "$sweep_skipped" -gt 0 ]; then
      ok "notebooklm dedupe sweep: 0 duplicates across $((8 - sweep_skipped))/8 notebooks ($sweep_skipped skipped)"
    fi
    # If sweep_dirty is non-empty, individual warns above already covered it.
  fi
fi
echo ""

# ── [6/7] Antigravity ───────────────────────────────────
echo "[6/7] Antigravity (multi-model IDE)"
begin_tool "antigravity" "Antigravity" "IDE"
skip "not session-critical for Cowork agents; Matt's local IDE"
echo ""

# ── [7/7] Paperclip ─────────────────────────────────────
echo "[7/7] Paperclip (agent coordination)"
begin_tool "paperclip" "Paperclip" "Coordination"
skip "deployment in progress (task #38) — add real check when Paperclip is live"
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
' "${TOOL_STATES[@]}" "$(whoami)@$(hostname -s 2>/dev/null || echo unknown)")

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

# ── Verdict ─────────────────────────────────────────────
echo "───────────────────────────────────────────────────────"
echo "  green: $GREEN   yellow: $YELLOW   red: $RED"
echo ""

if [ "$RED" -gt 0 ]; then
  echo "  ✗ VERDICT: BLOCK — do NOT start work"
  echo ""
  echo "  Blockers (fix first):"
  for b in "${BLOCKERS[@]}"; do echo "    - $b"; done
  if [ "$YELLOW" -gt 0 ]; then
    echo ""
    echo "  Warnings:"
    for w in "${WARNINGS[@]}"; do echo "    - $w"; done
  fi
  echo ""
  echo "  Before resuming work: fix blockers above, follow the USAGE REMINDERS."
  echo "═══════════════════════════════════════════════════════"
  exit 2
elif [ "$YELLOW" -gt 0 ]; then
  echo "  ⚠ VERDICT: WARN — $YELLOW drift finding(s)"
  echo ""
  echo "  Warnings (report to Matt, may proceed with acknowledgement):"
  for w in "${WARNINGS[@]}"; do echo "    - $w"; done
  echo ""
  echo "  Proceed with the USAGE REMINDERS above as your routing contract."
  echo "═══════════════════════════════════════════════════════"
  exit 1
else
  echo "  ✓ VERDICT: READY — all limitless-stack tools green. Proceed."
  echo "  Follow the USAGE REMINDERS above for every tool interaction this session."
  echo "═══════════════════════════════════════════════════════"
  exit 0
fi
