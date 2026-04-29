#!/usr/bin/env python3.11
"""
tools/cowork-fabrication-scanner.py

Forensic post-hoc scanner for fabrication in Cowork transcripts.

WHY THIS EXISTS:
    The original fabrication guard (.claude/hooks/check-fabrication.sh) is a
    Claude Code Stop hook. It only fires when Claude Code wraps up a turn —
    NOT when Cowork wraps up a turn. Matt mostly operates in Cowork mode, so
    the Stop hook log has been empty for 3 days. This scanner walks the Cowork
    transcript JSONLs that Cowork writes to disk on the Mac, extracts every
    computer:// URL Claude has emitted, verifies each path on disk, and appends
    findings to the same .claude/hooks/fabrication-log.jsonl that the Stop hook
    writes to. fabrication-review.sh then reads both sources transparently.

WHERE COWORK STORES TRANSCRIPTS (Mac):
    ~/Library/Application Support/Claude/
        local-agent-mode-sessions/<uuid>/<uuid>/local_<uuid>/
            .claude/projects/<encoded-cwd>/<session-uuid>.jsonl

    Each line is one event. Types we care about: "assistant" (the only type
    that contains Claude's outgoing message). Assistant entries have
    message.content as a list of blocks; we extract URLs ONLY from blocks
    whose type is "text" (not "thinking" — those are internal scratch and
    don't go to the user, so a fake link there has no fabrication impact).

WHERE THIS SCRIPT MUST RUN:
    On Matt's Mac. The Cowork session directory is not mounted into the
    sandbox. Invoke via desktop-commander or a Mac-side scheduled task.

IDEMPOTENCY:
    State file at tools/.cowork-fabrication-scanner-state.json keyed by
    transcript path with {mtime, line_count}. Re-runs only process lines
    appended since the last scan. If a transcript shrinks (e.g. truncation,
    rotation) we re-process from the start — safer to log the same finding
    twice than to miss a real fabrication.

OUTPUT FORMAT:
    Each fabrication-log.jsonl line is a JSON object compatible with the
    Stop hook's format, plus a "source": "cowork-scanner" field and
    transcript/line metadata so reviewers can trace findings back to the
    exact Cowork turn:

        {"ts": "...", "session": "cowork:<session-uuid>",
         "source": "cowork-scanner",
         "transcript": "/abs/path/<session-uuid>.jsonl",
         "line": 437,
         "mode": "scan",
         "status": "clean" | "dirty",
         "missing": [{"url": "...", "path": "..."}, ...],
         "total_urls": N}
"""

import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────

# The vault root — script lives at <vault>/tools/, so parent of parent.
SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parent
LOG_PATH = VAULT / ".claude" / "hooks" / "fabrication-log.jsonl"
STATE_PATH = SCRIPT_DIR / ".cowork-fabrication-scanner-state.json"

# Cowork transcript glob (Mac).
COWORK_BASE = Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
TRANSCRIPT_GLOB = str(
    COWORK_BASE / "*" / "*" / "local_*" / ".claude" / "projects" / "*" / "*.jsonl"
)


# ──────────────────────────────────────────────────────────────────────────
# URL extraction — same semantics as the patched check-fabrication.sh, plus
# two scanner-specific refinements forced by what real Cowork transcripts
# contain:
#
#   1. Bare-URL terminator class excludes backticks and quotes. Without this,
#      Claude writing things like `` `computer://` `` (literally talking
#      about the URL scheme inside markdown code-quotes) generates a fake
#      "fabrication" finding for every meta-discussion. Empirically the #1
#      false-positive class in our first scan.
#
#   2. After matching, strip trailing sentence punctuation (`,.;:!?`) — these
#      are almost never part of a real path; they're prose punctuation that
#      ran into a bare URL.
#
# Two forms: markdown-link [text](computer://path) and bare computer://path.
# We extract markdown-link URLs first (URL ends at ')'), then strip them
# from the text before the bare-URL scan to avoid double-counting.
# ──────────────────────────────────────────────────────────────────────────

MD_LINK_RE = re.compile(r'\]\((computer://[^)]+)\)')
# Excluded terminators: whitespace, ) > ] ` " ' and the Unicode ellipsis …
# (which Claude uses as a prose placeholder, e.g. "the URL was computer://…").
BARE_URL_RE = re.compile(r'computer://[^\s)>\]`"\'…]+')

# Trailing characters to strip from any matched URL — prose punctuation that
# almost certainly bled into the regex match.
TRAILING_PUNCT = ',.;:!?'

# A URL's path-component must contain at least one alphanumeric character to
# be treated as a real path. Anything that's pure punctuation (e.g. `/…`,
# `/...`, `/"`) is almost certainly a regex artifact from prose, not a path
# Claude meant to link.
PATH_HAS_ALNUM_RE = re.compile(r'[A-Za-z0-9]')


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for m in MD_LINK_RE.finditer(text):
        urls.append(m.group(1).rstrip(TRAILING_PUNCT))
    text_stripped = MD_LINK_RE.sub(']', text)
    for m in BARE_URL_RE.finditer(text_stripped):
        urls.append(m.group(0).rstrip(TRAILING_PUNCT))
    # Discard scheme-only and pure-punctuation paths.
    cleaned = []
    for u in urls:
        if not u.startswith("computer://") or u == "computer://":
            continue
        path_part = u[len("computer://"):]
        if not PATH_HAS_ALNUM_RE.search(path_part):
            continue
        cleaned.append(u)
    # Dedupe preserving order.
    return list(dict.fromkeys(cleaned))


# ──────────────────────────────────────────────────────────────────────────
# Path resolution — Mac-side translation for Cowork sandbox-mount paths.
#
# The hook (check-fabrication.sh) runs INSIDE a Cowork sandbox, so paths
# like /sessions/inspiring-friendly-cray/mnt/obsidian /... resolve as-is
# (the sandbox literally has those directories). This scanner runs on the
# MAC, where those /sessions/... paths don't exist as directories — they
# only exist as bind-mounts inside whichever sandbox emitted them. But the
# user CAN click computer:///sessions/<sandbox>/mnt/obsidian /... links and
# they resolve to the real Mac vault folder via Cowork's mount layer.
#
# So before declaring a path missing, we try translating
#   /sessions/<anything>/mnt/obsidian /<rest>
# to
#   <MAC_VAULT_ROOT>/<rest>
# and check that. If the translated path exists, the original URL is fine.
#
# MAC_VAULT_ROOT is auto-detected from the script's own location (since
# this file lives in <vault>/tools/), which means the script self-configures
# regardless of where the vault folder is on disk.
# ──────────────────────────────────────────────────────────────────────────

MAC_VAULT_ROOT = str(VAULT)
VAULT_MOUNT_RE = re.compile(r'^/sessions/[^/]+/mnt/obsidian (/.*)?$')
# Anything else under /sessions/<name>/ is sandbox-internal — either a mount
# we don't know how to translate (e.g. /sessions/foo/mnt/OpenFirehouse/…)
# or sandbox scratch (/sessions/foo/.tmp/…). The Mac scanner can't see those.
ANY_SANDBOX_RE = re.compile(r'^/sessions/[^/]+/')


def url_to_path(u: str) -> str:
    p = u[len("computer://"):]
    p = urllib.parse.unquote(p)
    if not p.startswith("/"):
        p = "/" + p
    return p


def check_path(p: str) -> str:
    """Return one of:
       - 'exists': the file exists (either as-is on Mac, or via vault-mount translation)
       - 'missing': the file doesn't exist and we CAN verify that authoritatively
       - 'unverifiable': the path is a sandbox-internal path we can't reach from the Mac
                        (e.g. another Cowork session's mount or .tmp). Don't blame Claude
                        for these — they may have been real at write-time, we just can't tell."""
    if os.path.exists(p):
        return "exists"
    m = VAULT_MOUNT_RE.match(p)
    if m:
        rest = m.group(1) or ""
        translated = MAC_VAULT_ROOT + rest
        if os.path.exists(translated):
            return "exists"
        # The vault mount IS translatable, so a missing file here is authoritative.
        return "missing"
    if ANY_SANDBOX_RE.match(p):
        # Sandbox-internal path from a different session — can't verify.
        return "unverifiable"
    # Plain Mac path — authoritative.
    return "missing"


# ──────────────────────────────────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(STATE_PATH)


# ──────────────────────────────────────────────────────────────────────────
# Per-line processing
# ──────────────────────────────────────────────────────────────────────────

def extract_assistant_text(line_obj: dict) -> str:
    """Return concatenated text of all 'text' blocks in an assistant entry.
    Skip 'thinking' blocks — those are internal and never reach the user."""
    if line_obj.get("type") != "assistant":
        return ""
    msg = line_obj.get("message") or {}
    content = msg.get("content")
    # content can be: a string (rare/legacy), or a list of blocks
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts)


def scan_transcript(transcript_path: str, start_line: int, dry_run: bool):
    """Yield (line_number, log_entry_dict) tuples for every assistant turn
    after `start_line` that contained at least one computer:// URL."""
    session_uuid = Path(transcript_path).stem
    line_no = 0
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line_no += 1
            if line_no <= start_line:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            text = extract_assistant_text(obj)
            if not text:
                continue
            urls = extract_urls(text)
            if not urls:
                continue
            missing = []
            unverifiable = 0
            for u in urls:
                p = url_to_path(u)
                status = check_path(p)
                if status == "missing":
                    missing.append({"url": u, "path": p})
                elif status == "unverifiable":
                    unverifiable += 1
                # 'exists' → drop silently, that's what we want
            # If every URL was unverifiable AND there are no missing, skip
            # logging this turn entirely — there's nothing actionable.
            verifiable_urls = len(urls) - unverifiable
            if verifiable_urls == 0:
                continue
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session": f"cowork:{session_uuid}",
                "source": "cowork-scanner",
                "transcript": transcript_path,
                "line": line_no,
                "mode": "scan",
                "status": "clean" if not missing else "dirty",
                "missing": missing,
                "total_urls": verifiable_urls,
                "unverifiable_urls": unverifiable,
            }
            yield line_no, entry
    return line_no  # not actually used — generator return ignored


def count_lines(path: str) -> int:
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            n += 1
    return n


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan and report; do NOT write log entries or update state.")
    ap.add_argument("--from-scratch", action="store_true",
                    help="Ignore state file; rescan every transcript from line 1.")
    ap.add_argument("--limit", type=int, default=0,
                    help="If >0, only scan the N most recently modified transcripts.")
    ap.add_argument("--quiet", action="store_true", help="Only print summary line.")
    args = ap.parse_args()

    if not COWORK_BASE.exists():
        print(f"[fatal] Cowork session base not found: {COWORK_BASE}", file=sys.stderr)
        print(f"        This script must run on the Mac where Cowork stores transcripts.",
              file=sys.stderr)
        return 2

    transcripts = sorted(glob.glob(TRANSCRIPT_GLOB), key=lambda p: os.path.getmtime(p))
    if args.limit and args.limit > 0:
        transcripts = transcripts[-args.limit:]

    if not transcripts:
        print(f"[info] No transcripts found under {COWORK_BASE}")
        return 0

    state = {} if args.from_scratch else load_state()
    new_state = dict(state)

    total_scanned_lines = 0
    total_new_entries = 0
    total_dirty = 0
    total_clean = 0
    per_file = []

    log_fh = None
    if not args.dry_run:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(LOG_PATH, "a")

    try:
        for tp in transcripts:
            try:
                mtime = os.path.getmtime(tp)
            except FileNotFoundError:
                continue

            prev = state.get(tp) or {}
            prev_mtime = prev.get("mtime")
            prev_lines = prev.get("line_count", 0)

            # Skip if file hasn't grown AND mtime is unchanged.
            if prev_mtime is not None and mtime == prev_mtime:
                # Still record per-file zero so report is complete.
                per_file.append((tp, 0, 0, 0, "unchanged"))
                continue

            # Detect truncation/rotation: if current line count is < prev_lines,
            # rescan from start.
            current_lines = count_lines(tp)
            if current_lines < prev_lines:
                start_line = 0
                note = f"shrank ({prev_lines}→{current_lines}); rescanned from start"
            else:
                start_line = prev_lines
                note = f"new lines: {current_lines - prev_lines}"

            file_entries = 0
            file_dirty = 0
            file_clean = 0

            for line_no, entry in scan_transcript(tp, start_line, args.dry_run):
                file_entries += 1
                total_new_entries += 1
                if entry["status"] == "dirty":
                    file_dirty += 1
                    total_dirty += 1
                else:
                    file_clean += 1
                    total_clean += 1
                if log_fh is not None:
                    log_fh.write(json.dumps(entry) + "\n")

            total_scanned_lines += max(0, current_lines - start_line)
            per_file.append((tp, file_entries, file_dirty, file_clean, note))

            # Update state for this transcript.
            new_state[tp] = {"mtime": mtime, "line_count": current_lines}
    finally:
        if log_fh is not None:
            log_fh.close()

    # Persist state unless dry-run.
    if not args.dry_run:
        save_state(new_state)

    # ── Report ──
    if not args.quiet:
        print("=" * 68)
        print(f"COWORK FABRICATION SCANNER — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        print("=" * 68)
        print(f"Transcripts considered: {len(transcripts)}")
        print(f"Lines scanned (new):    {total_scanned_lines}")
        print(f"URL-bearing turns:      {total_new_entries}")
        print(f"  clean:                {total_clean}")
        print(f"  dirty:                {total_dirty}")
        if args.dry_run:
            print("(dry-run: no log entries written, state not updated)")
        print()
        print("── Per-transcript ──")
        for tp, n, d, c, note in per_file:
            short = "/".join(Path(tp).parts[-4:])
            print(f"  {short}  +{n} entries (clean={c} dirty={d}) — {note}")
    else:
        print(f"scanned={len(transcripts)} new_entries={total_new_entries} "
              f"clean={total_clean} dirty={total_dirty}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
