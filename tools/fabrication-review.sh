#!/bin/bash
# tools/fabrication-review.sh
#
# Readiness check for flipping .claude/hooks/check-fabrication.sh from log-only
# to enforce mode. Reads .claude/hooks/fabrication-log.jsonl and produces:
#   - entry counts (total, clean, dirty, URLs checked)
#   - every "missing path" finding with heuristic classification
#   - verdict: READY / NEED MORE DATA / REGEX BUGS TO FIX
#
# Usage:
#   bash tools/fabrication-review.sh
#
# Entry criteria (from wiki/log.md + task #10):
#   1. ≥20 URL-bearing Stop events logged (denominator)
#   2. Zero unresolved REGEX-BUG findings (false positives would block
#      legitimate wrap-ups and erode trust in the gate)
#   3. At least one REAL-FAB catch is nice-to-have, not required

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$VAULT/.claude/hooks/fabrication-log.jsonl"
MODE_FILE="$VAULT/.claude/hooks/fabrication-mode"

if [ ! -r "$LOG" ]; then
  echo "No fabrication log yet at $LOG"
  echo "The hook only writes entries for messages that contain computer:// URLs."
  echo "Once you've run a few sessions with file-linking wrap-ups, re-run this."
  exit 0
fi

CURRENT_MODE="log"
if [ -r "$MODE_FILE" ]; then
  CURRENT_MODE=$(tr -d ' \n\r' <"$MODE_FILE")
fi

LOG_PATH="$LOG" MODE="$CURRENT_MODE" VAULT="$VAULT" python3 - <<'PYEOF'
import os, json, sys
from collections import Counter

log_path = os.environ["LOG_PATH"]
current_mode = os.environ["MODE"]
vault = os.environ["VAULT"]

entries = []
with open(log_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

total = len(entries)
# Backwards-compat: older entries didn't have "status" field
clean = sum(1 for e in entries if e.get("status") == "clean")
dirty = sum(1 for e in entries if e.get("status") == "dirty" or (e.get("status") is None and e.get("missing")))
urls_checked = sum(e.get("total_urls", 0) for e in entries)

# Collect all missing-path findings (may be multiple per entry)
findings = []
for e in entries:
    for m in e.get("missing", []):
        findings.append({
            "ts": e.get("ts"),
            "session": e.get("session"),
            "url": m.get("url"),
            "path": m.get("path"),
        })

def classify(path):
    """Return (category, reason). Categories:
       REGEX-BUG-LIKELY — likely false positive, patch the regex before flipping
       ENCODING          — URL encoding issue, check decoding
       REAL-FAB-LIKELY   — Claude probably invented this path
       UNCLEAR           — needs human review (parent missing too)
    """
    if not path:
        return ("UNCLEAR", "empty path")
    if "%" in path:
        return ("ENCODING", "path contains % — check URL encoding")
    ext = os.path.splitext(path)[1]
    parent = os.path.dirname(path)
    parent_exists = bool(parent) and os.path.exists(parent)
    # Path with no extension is suspicious — most fabricated file refs have one
    if not ext:
        if parent_exists:
            return ("REGEX-BUG-LIKELY",
                    "no file extension + parent dir exists — URL likely truncated mid-path")
        else:
            return ("REGEX-BUG-LIKELY",
                    "no file extension + parent dir also missing — likely mid-path truncation")
    # Has extension
    if parent_exists:
        return ("REAL-FAB-LIKELY",
                f"has '{ext}' extension, parent dir exists, file is missing")
    return ("UNCLEAR",
            f"has '{ext}' extension but parent dir also missing — typo or fabrication?")

# Classify every finding
classifications = []
for f in findings:
    cat, reason = classify(f["path"])
    classifications.append((cat, reason, f))

by_cat = Counter(c[0] for c in classifications)

# ─── Output ───
print("=" * 68)
print("FABRICATION REVIEW — readiness for flip-to-enforce")
print("=" * 68)
print(f"Log: {log_path}")
print(f"Current mode: {current_mode}")
print()
print("── Volume ──")
print(f"  Total URL-bearing Stop events logged: {total}")
print(f"    clean (all URLs resolved):          {clean}")
print(f"    dirty (at least one missing):       {dirty}")
print(f"  Total URLs checked:                   {urls_checked}")
print(f"  Total missing-path findings:          {len(findings)}")
print()

if classifications:
    print("── Findings by category ──")
    for cat in ["REGEX-BUG-LIKELY", "ENCODING", "UNCLEAR", "REAL-FAB-LIKELY"]:
        n = by_cat.get(cat, 0)
        if n:
            print(f"  {cat:<20s} {n}")
    print()
    print("── Finding detail ──")
    for i, (cat, reason, f) in enumerate(classifications, 1):
        tag = {
            "REGEX-BUG-LIKELY": "⚠ REGEX",
            "ENCODING":         "⚠ ENCODE",
            "UNCLEAR":          "? UNCLEAR",
            "REAL-FAB-LIKELY":  "✓ REAL-FAB",
        }.get(cat, "?")
        print(f"[{i:>3}] {tag}  {f['ts']}  session={f['session']}")
        print(f"       url:    {f['url']}")
        print(f"       path:   {f['path']}")
        print(f"       reason: {reason}")
        print()

# ─── Verdict ───
print("=" * 68)
print("VERDICT")
print("=" * 68)

MIN_EVENTS = 20
regex_bugs = by_cat.get("REGEX-BUG-LIKELY", 0) + by_cat.get("ENCODING", 0)
real_fabs = by_cat.get("REAL-FAB-LIKELY", 0)
unclear = by_cat.get("UNCLEAR", 0)

if regex_bugs > 0:
    print(f"Status: NEEDS FIX — {regex_bugs} regex / encoding bug(s) to resolve first.")
    print("Action: investigate REGEX-BUG-LIKELY and ENCODING entries above.")
    print("        Patch check-fabrication.sh, purge the log, re-run.")
    print("        Do not flip enforce mode while false positives exist —")
    print("        a single FP blocks a legitimate wrap-up and breaks trust.")
elif total < MIN_EVENTS:
    remaining = MIN_EVENTS - total
    print(f"Status: NEED MORE DATA — {total}/{MIN_EVENTS} URL-bearing events logged.")
    print(f"Action: run ~{remaining} more sessions that link files, then re-check.")
elif unclear > 0:
    print(f"Status: NEEDS TRIAGE — {unclear} UNCLEAR finding(s) need human classification.")
    print("Action: for each UNCLEAR entry, decide if it's a real fabrication or a")
    print("        regex bug, then act accordingly.")
else:
    extra = f" ({real_fabs} real fabrication{'s' if real_fabs != 1 else ''} caught)" if real_fabs else " (clean log)"
    print(f"Status: READY TO FLIP{extra}")
    print(f"        {total} events logged, 0 regex bugs, 0 encoding issues.")
    print()
    print("Action — on Matt's Mac:")
    print(f"  echo 'enforce' > {vault}/.claude/hooks/fabrication-mode")
    print()
    print("Then append a schema entry to wiki/log.md marking the flip with:")
    print("  - date / event that triggered it")
    print("  - before/after fabrication counts from this review")
    print("  - confirmation that .claude/hooks/README.md reflects the new default")

print()
PYEOF
