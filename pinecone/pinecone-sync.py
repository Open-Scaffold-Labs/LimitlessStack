#!/usr/bin/env python3.11
"""
Sync the OpenScaffold raw/ corpus into the Pinecone `openscaffold` index.

Usage:
    python3.11 tools/pinecone-sync.py                  # full sync (slow first time)
    python3.11 tools/pinecone-sync.py --changed-only   # only files modified since last sync (fast)
    python3.11 tools/pinecone-sync.py --dry-run        # list what would be sent
    python3.11 tools/pinecone-sync.py --repo FireHazmat # sync one repo only

Reads the Pinecone API key from macOS Keychain entry (service=pinecone-api-key).
Embeds via Pinecone-hosted multilingual-e5-large.
State file: <vault>/tools/.pinecone-sync-state.json — tracks last-synced mtime per file.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

# --- config ---
VAULT = Path(__file__).resolve().parent.parent
RAW_REPOS = VAULT / "raw" / "openscaffold-repos"
STATE_FILE = Path(__file__).resolve().parent / ".pinecone-sync-state.json"
INDEX_NAME = "openscaffold"
NAMESPACE = "repos"
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
BATCH_SIZE = 96  # Pinecone upsert max

# Pinecone hosted-embedding rate limits (multilingual-e5-large, free Starter tier):
#   250,000 tokens / minute, input_type=passage
# Conservative chars-per-token estimate; safety margin under 250k.
CHARS_PER_TOKEN = 4
TOKENS_PER_MINUTE_LIMIT = 200_000  # leave 50k headroom
SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", ".expo", "ios", "android", ".vercel", "__pycache__", ".pytest_cache", "coverage"}
TEXT_EXTS = {".md", ".txt", ".js", ".jsx", ".ts", ".tsx", ".py", ".json", ".yml", ".yaml", ".toml", ".css", ".html", ".sql", ".sh", ".env.example"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
MAX_FILE_BYTES = 2_000_000  # skip files > 2MB


def get_api_key() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "pinecone-api-key", "-w"],
        capture_output=True, text=True, check=True
    ).stdout.strip()


def read_file_text(path: Path) -> str | None:
    """Return file text content, or None if unreadable / unsupported."""
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    ext = path.suffix.lower()
    if ext in TEXT_EXTS or path.name in {"README", "LICENSE", "CHANGELOG", "Dockerfile"}:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
    if ext in DOCX_EXTS:
        try:
            from docx import Document
            doc = Document(path)
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            print("(install python-docx for .docx support: pip3.11 install python-docx --break-system-packages)", file=sys.stderr)
            return None
        except Exception:
            return None
    if ext in PDF_EXTS:
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            return None
        except Exception:
            return None
    return None


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP):
    text = text.strip()
    if not text:
        return
    i = 0
    while i < len(text):
        yield text[i:i+size]
        if i + size >= len(text):
            break
        i += size - overlap


def iter_files(root: Path, repo_filter: str | None):
    for repo_dir in sorted(root.iterdir()):
        if not repo_dir.is_dir():
            continue
        if repo_filter and repo_dir.name != repo_filter:
            continue
        for path in repo_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            yield repo_dir.name, path


def make_record(repo: str, path: Path, chunk_idx: int, chunk: str) -> dict:
    rel = path.relative_to(RAW_REPOS / repo).as_posix()
    rec_id = hashlib.sha1(f"{repo}|{rel}|{chunk_idx}".encode()).hexdigest()
    return {
        "_id": rec_id,
        "chunk_text": chunk,
        "repo": repo,
        "path": rel,
        "ext": path.suffix.lower(),
        "chunk_index": chunk_idx,
    }


def upsert_with_rate_limit(index, namespace, batch, token_window: deque, dry_run: bool):
    """Upsert one batch, sleeping if needed to stay under the per-minute token limit. Retries on 429."""
    batch_tokens = sum(len(r["chunk_text"]) for r in batch) // CHARS_PER_TOKEN
    now = time.time()

    # Drop window entries older than 60s
    while token_window and now - token_window[0][0] > 60:
        token_window.popleft()
    used = sum(t for _, t in token_window)

    if used + batch_tokens > TOKENS_PER_MINUTE_LIMIT and token_window:
        sleep_for = 60 - (now - token_window[0][0]) + 0.5
        if sleep_for > 0:
            print(f"  rate-limit sleep {sleep_for:.1f}s (window: {used} tokens used, +{batch_tokens} pending)")
            time.sleep(sleep_for)
            now = time.time()
            while token_window and now - token_window[0][0] > 60:
                token_window.popleft()

    if dry_run:
        token_window.append((now, batch_tokens))
        return

    # Upsert with 429 retry/backoff
    delay = 5
    for attempt in range(6):
        try:
            index.upsert_records(namespace, batch)
            token_window.append((time.time(), batch_tokens))
            return
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                print(f"  429 hit, sleeping {delay}s (attempt {attempt+1}/6)")
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
    raise RuntimeError("Exceeded retries on 429")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", help="only sync this repo")
    parser.add_argument("--changed-only", action="store_true",
                        help="only sync files modified since last successful sync")
    parser.add_argument("--reset-state", action="store_true",
                        help="wipe the sync state (forces full re-sync next run)")
    parser.add_argument("--seed-state", action="store_true",
                        help="record current mtimes WITHOUT uploading (use after a manual full sync)")
    args = parser.parse_args()

    if args.reset_state:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print(f"state cleared: {STATE_FILE}")
        return

    if args.seed_state:
        seeded = {}
        for repo, path in iter_files(RAW_REPOS, args.repo):
            rel_key = f"{repo}/{path.relative_to(RAW_REPOS / repo).as_posix()}"
            seeded[rel_key] = path.stat().st_mtime
        save_state(seeded)
        print(f"seeded state with {len(seeded)} files: {STATE_FILE}")
        return

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index(INDEX_NAME)

    state = load_state() if args.changed_only else {}
    new_state = dict(state)

    batch = []
    files = 0
    chunks_total = 0
    skipped = 0
    unchanged = 0
    token_window: deque = deque()

    for repo, path in iter_files(RAW_REPOS, args.repo):
        rel_key = f"{repo}/{path.relative_to(RAW_REPOS / repo).as_posix()}"
        mtime = path.stat().st_mtime
        if args.changed_only and state.get(rel_key) == mtime:
            unchanged += 1
            continue

        text = read_file_text(path)
        if text is None or not text.strip():
            skipped += 1
            continue
        files += 1
        for i, chunk in enumerate(chunk_text(text)):
            batch.append(make_record(repo, path, i, chunk))
            chunks_total += 1
            if len(batch) >= BATCH_SIZE:
                upsert_with_rate_limit(index, NAMESPACE, batch, token_window, args.dry_run)
                action = "would upsert" if args.dry_run else "upserted"
                print(f"  {action} batch ({len(batch)})  total chunks: {chunks_total}  files: {files}")
                batch = []
        new_state[rel_key] = mtime

    if batch:
        upsert_with_rate_limit(index, NAMESPACE, batch, token_window, args.dry_run)
        action = "would upsert" if args.dry_run else "upserted"
        print(f"  {action} final batch ({len(batch)})")

    if not args.dry_run:
        save_state(new_state)

    print(f"\nDONE  files: {files}  chunks: {chunks_total}  skipped: {skipped}  unchanged: {unchanged}  dry_run: {args.dry_run}")


if __name__ == "__main__":
    main()
