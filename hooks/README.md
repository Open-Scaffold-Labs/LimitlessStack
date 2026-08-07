# Hooks — hard gates for the Limitless Stack

Runtime-enforced by Claude Code / Cowork via `.claude/settings.json`.
These close loops that USAGE REMINDERS (the soft layer) can't enforce on their own.

## The four hooks

| Hook | Event | What it does | Mode |
|---|---|---|---|
| `session-start.sh` | SessionStart | Sandbox-side preflight (CLAUDE.md / wiki / git) + MANDATORY Skill(roll-call) reminder + USAGE REMINDERS + hard-gates roster. Fires on startup/resume/clear/compact. | always on |
| `check-bash.sh` | PreToolUse (matcher: Bash) | Denies known-dead-end commands: `pip install notebooklm-py`, `pip install playwright`, `playwright install`, bare `notebooklm ...` in sandbox Bash. Returns `permissionDecision: "deny"` with reason that points at desktop-commander routing. | always on |
| `audit-tool.sh` | PostToolUse (matcher: *) | Logs every tool call as JSONL (`tool-audit.jsonl`). Fields: ts, session, tool, input summary (500 chars), response_len. Pure observability — no enforcement. Feeds future pattern-mining. | always on |
| `check-fabrication.sh` | Stop (matcher: *) | Scans outgoing messages for `computer://` URLs, verifies each path exists. Detects both markdown-link `[text](computer://...)` and bare-URL forms. Handles spaces in vault path. URL-decodes (%20). Excludes backticks/quotes/ellipsis from the bare-URL terminator class. Logs every URL-bearing message (clean or dirty) so the flip-to-enforce review has a denominator. | **log** (default) / enforce |

## Two data sources, one log

The fabrication guard has TWO ingest paths into `.claude/hooks/fabrication-log.jsonl`:

1. **Stop hook** (`check-fabrication.sh`, table above) — fires only when a Claude Code session wraps up. Synchronous; can block in enforce mode.
2. **Cowork transcript scanner** (`tools/cowork-fabrication-scanner.py`) — forensic post-hoc walk over Cowork session transcripts at `~/Library/Application Support/Claude/local-agent-mode-sessions/.../*.jsonl`. Idempotent (state file at `tools/.cowork-fabrication-scanner-state.json` keyed by transcript path with mtime + line count). Adds `"source": "cowork-scanner"`, `"transcript"`, and `"line"` fields to each log entry so reviewers can trace findings back to the exact Cowork turn.

This dual-source design exists because Matt operates mostly in Cowork mode, and Cowork doesn't fire Claude Code Stop hooks. Without the scanner, the log starves and the flip-to-enforce review can't make progress. Both data sources keep their URL-extraction regex and URL-decoding semantics in sync — patch one, patch the other.

### Path resolution from the Mac

The Stop hook runs inside a Cowork sandbox, so `/sessions/<sandbox>/mnt/obsidian /...` paths exist as-is and resolve directly. The scanner runs on the Mac, which doesn't have those `/sessions/...` directories. So the scanner adds two pieces of resolution logic:

- **Vault-mount translation**: paths matching `/sessions/<anything>/mnt/obsidian /<rest>` get translated to `<MAC_VAULT_ROOT>/<rest>` (the script's own parent-of-parent) before existence-checking. This is how the scanner verifies user-clickable vault links from sessions other than its own.
- **Unverifiable categorization**: paths under `/sessions/<sandbox>/mnt/<not-obsidian>/...` or `/sessions/<sandbox>/.tmp/...` are sandbox-internal to a session that's no longer running. The scanner can't tell whether they were real at write-time. These get tracked in a separate `unverifiable_urls` counter on the log entry — not flagged as missing, not blamed on Claude. Turns whose URLs are 100% unverifiable are skipped entirely (nothing actionable).

## Modes

`check-fabrication.sh` reads `.claude/hooks/fabrication-mode` (single word, `log` or `enforce`).
- **log** — write an entry to `fabrication-log.jsonl` for every URL-bearing message (`status: "clean"` or `status: "dirty"`), exit clean. Used to gather coverage + false-positive rate before flipping. No-URL messages fast-path without logging.
- **enforce** — emit `{"decision":"block","reason":"..."}` on stdout when missing paths are found, which Claude Code treats as a wrap-up block.

The mode flag only affects the Stop hook. The scanner is always forensic.

### Readiness check for flipping — `tools/fabrication-review.sh`

Run `bash tools/fabrication-review.sh` — it reads the log (both sources transparently), classifies each missing-path finding heuristically (REGEX-BUG-LIKELY / ENCODING / UNCLEAR / REAL-FAB-LIKELY), and prints one of four verdicts:

- **NEEDS FIX** — regex / encoding bugs exist. Patch `check-fabrication.sh` AND `tools/cowork-fabrication-scanner.py` (keep regex parity), purge the log, re-run. Do NOT flip while FPs are outstanding — a single FP blocks a legitimate wrap-up and erodes trust in the gate.
- **NEED MORE DATA** — fewer than 20 URL-bearing events logged. Keep running sessions; the scanner will pick up new Cowork transcripts on its next scheduled run.
- **NEEDS TRIAGE** — UNCLEAR findings exist; need human classification.
- **READY TO FLIP** — ≥20 events, zero regex bugs, no UNCLEAR findings. Then:
  ```
  echo "enforce" > .claude/hooks/fabrication-mode
  ```
  Append a schema entry to `wiki/log.md` documenting the flip, and update this README to reflect that enforce is the new default.

The flip is tracked as task #10 in the session TaskList. It's the milestone where the fabrication guard transitions from **forensic** (detect after the fact) to **preventive** (block in-flight).

### Schedule

The `fabrication-review-weekly` Cowork scheduled task runs the scanner first (idempotent ingest), then the review, every Monday at 9:07 AM local time. Schedule + prompt at `~/Documents/Claude/Scheduled/fabrication-review-weekly/SKILL.md`.

## Design rules

1. **Fail open.** Every script exits 0 on parse failure. A broken hook must never break the session.
2. **Python inline, no jq.** Heredoc `python3 - <<'PYEOF'` with env-var-pass for input (not stdin into the python, since stdin is already consumed by the shell `read`).
3. **Idempotent.** Running a hook twice with the same input is safe.
4. **Sandbox-aware.** Session-start does partial preflight — the full preflight needs Mac-native tools (Keychain, notebooklm CLI) and must route via desktop-commander. The hook reminds Claude to invoke `Skill(roll-call)`.

## Log files (gitignored)

- `tool-audit.jsonl` — every tool call, one JSON per line. Grows indefinitely; rotate manually if it gets large.
- `fabrication-log.jsonl` — fabrication findings. Used to tune the regex + decide when to flip to enforce.
- `fabrication-mode` — single-word mode override. Defaults to "log" if missing.

## Testing

All four scripts were tested with mock JSON input before deployment:
- `session-start.sh`: ran standalone, verified preflight output
- `check-bash.sh`: 5 cases (allow, 3 deny patterns, non-Bash tool)
- `audit-tool.sh`: verified JSONL append
- `check-fabrication.sh`: 5 cases (real path, fake path in log mode, fake path in enforce mode, no URLs, markdown-link with space in path)

## Self-improvement loop

Every ~week, pattern-mine `tool-audit.jsonl` for:
- Repeated anti-patterns that weren't caught → add a new `check-bash.sh` rule
- Tool-call sequences that correlate with fabrication findings → refine `check-fabrication.sh`
- Startups where Roll Call was skipped → tighten the SessionStart reminder

New rules land here, get committed, and propagate to every new session via SessionStart.

## Related tools

- `tools/fabrication-review.sh` — readiness check for the flip-to-enforce milestone. Reads the fabrication log, classifies findings, emits a verdict.
- `tools/limitless-preflight.sh` — the full Mac-side preflight (Keychain, Pinecone auth, NotebookLM freshness). Invoked via `Skill(roll-call)`.
