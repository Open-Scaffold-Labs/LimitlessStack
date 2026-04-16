#!/usr/bin/env python3.11
"""
Keep the 'OpenScaffold Wiki' NotebookLM notebook in sync with wiki/*.md.

Usage:
    python3 tools/notebooklm-wiki-refresh.py              # refresh: add new, refresh changed, delete removed
    python3 tools/notebooklm-wiki-refresh.py --seed       # first-time sync: match existing notebook sources by title, write state
    python3 tools/notebooklm-wiki-refresh.py --dry-run    # show what would happen, do nothing

State file at tools/.notebooklm-wiki-state.json maps path -> {mtime, source_id}.
Notebook ID is hard-coded below; change it if you replicate this to another vault.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
WIKI = VAULT / "wiki"
STATE_FILE = Path(__file__).resolve().parent / ".notebooklm-wiki-state.json"
NOTEBOOK_ID = "cdaa7a43"  # OpenScaffold Wiki notebook


def run_nb(args: list[str]) -> subprocess.CompletedProcess:
    """Run a notebooklm-py CLI command."""
    return subprocess.run(
        ["notebooklm"] + args,
        capture_output=True, text=True,
    )


def activate_notebook(nbid: str) -> None:
    """Set the current notebook context. Must be called before any source-* subcommand."""
    subprocess.run(["notebooklm", "use", nbid],
                   capture_output=True, text=True)


def check_auth() -> bool:
    """Verify NotebookLM auth is valid. Returns True if OK."""
    result = subprocess.run(["notebooklm", "auth", "check", "--test"],
                            capture_output=True, text=True)
    if result.returncode != 0 or "fail" in result.stdout.lower():
        print("AUTH EXPIRED — run 'notebooklm login' to re-authenticate.")
        return False
    return True


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def iter_wiki_files():
    for p in WIKI.rglob("*.md"):
        if p.name.startswith("."):
            continue
        yield p


def parse_source_list(output: str) -> dict:
    """Parse `notebooklm source list --json` into {title: source_id}."""
    title_to_id: dict[str, str] = {}
    try:
        data = json.loads(output)
    except Exception:
        return title_to_id
    # data shape: either a list of sources or {"sources": [...]}
    sources = data if isinstance(data, list) else data.get("sources", [])
    for s in sources:
        sid = s.get("id") or s.get("source_id")
        title = s.get("title") or s.get("name")
        if sid and title:
            title_to_id[title] = sid
    return title_to_id


def cmd_add(path: Path) -> str | None:
    """Add a file, return source_id or None."""
    result = run_nb(["source", "add", str(path)])
    out = result.stdout + result.stderr
    m = re.search(r"Added source:\s+([0-9a-f-]+)", out)
    return m.group(1) if m else None


def cmd_refresh(source_id: str) -> bool:
    result = run_nb(["source", "refresh", source_id])
    return result.returncode == 0


def cmd_delete(source_id: str) -> bool:
    result = run_nb(["source", "delete", source_id])
    return result.returncode == 0


def seed(dry_run: bool) -> None:
    """Match wiki files to existing notebook sources by filename (title). Write initial state."""
    print("Fetching existing notebook sources...")
    listing = run_nb(["source", "list", "--json"])
    title_to_id = parse_source_list(listing.stdout)
    print(f"  found {len(title_to_id)} existing sources")

    state = {}
    matched = 0
    unmatched = []
    for path in iter_wiki_files():
        title = path.name  # NotebookLM uses filename as title for text sources
        rel = path.relative_to(VAULT).as_posix()
        if title in title_to_id:
            state[rel] = {"mtime": path.stat().st_mtime, "source_id": title_to_id[title]}
            matched += 1
        else:
            unmatched.append(rel)

    print(f"  matched {matched} wiki files to notebook sources")
    if unmatched:
        print(f"  {len(unmatched)} wiki files have no match in the notebook:")
        for u in unmatched[:10]:
            print(f"    - {u}")
        if len(unmatched) > 10:
            print(f"    ... and {len(unmatched) - 10} more")

    if not dry_run:
        save_state(state)
        print(f"  wrote {STATE_FILE}")


def sync(dry_run: bool) -> None:
    state = load_state()
    if not state:
        print("ERROR: no state file. Run with --seed first.", file=sys.stderr)
        sys.exit(1)

    current_files = {p.relative_to(VAULT).as_posix(): p for p in iter_wiki_files()}
    new_state = dict(state)

    added = refreshed = deleted = unchanged = 0

    # Files that exist on disk
    for rel, path in current_files.items():
        mtime = path.stat().st_mtime
        entry = state.get(rel)
        if entry and entry["mtime"] == mtime:
            unchanged += 1
            continue
        if entry:
            # Changed file: refresh by source_id
            print(f"  ~ refresh {rel}")
            if not dry_run:
                ok = cmd_refresh(entry["source_id"])
                if ok:
                    new_state[rel] = {"mtime": mtime, "source_id": entry["source_id"]}
                    refreshed += 1
                else:
                    print(f"    refresh failed; will try delete + add")
                    cmd_delete(entry["source_id"])
                    sid = cmd_add(path)
                    if sid:
                        new_state[rel] = {"mtime": mtime, "source_id": sid}
                        refreshed += 1
            else:
                refreshed += 1
        else:
            # New file: add
            print(f"  + add {rel}")
            if not dry_run:
                sid = cmd_add(path)
                if sid:
                    new_state[rel] = {"mtime": mtime, "source_id": sid}
                    added += 1
            else:
                added += 1

    # Files that were in state but no longer on disk
    for rel in list(state.keys()):
        if rel not in current_files:
            print(f"  - delete {rel}")
            if not dry_run:
                if cmd_delete(state[rel]["source_id"]):
                    del new_state[rel]
                    deleted += 1
            else:
                deleted += 1

    if not dry_run:
        save_state(new_state)
    print(f"\nDONE  added: {added}  refreshed: {refreshed}  deleted: {deleted}  unchanged: {unchanged}  dry_run: {dry_run}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true",
                        help="first-time: match existing notebook sources to wiki files by title")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-auth-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_auth_check:
        if not check_auth():
            sys.exit(1)

    activate_notebook(NOTEBOOK_ID)

    if args.seed:
        seed(args.dry_run)
    else:
        sync(args.dry_run)


if __name__ == "__main__":
    main()
