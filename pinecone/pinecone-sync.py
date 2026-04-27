#!/usr/bin/env python3.11
"""
Sync the OpenScaffold corpus into the Pinecone `openscaffold` index.

Three corpora, each in its own namespace:
    repos     namespace=repos    (raw/openscaffold-repos/<repo>/**)      — source code + docs
    wiki      namespace=wiki     (wiki/**/*.md + CLAUDE.md + README.md)  — curated knowledge base
    uploads   namespace=uploads  (raw/uploads/**)                        — Matt's attachments

Usage:
    python3.11 tools/pinecone-sync.py                       # full sync of all corpora
    python3.11 tools/pinecone-sync.py --changed-only        # only files modified since last sync
    python3.11 tools/pinecone-sync.py --corpus wiki         # one corpus only
    python3.11 tools/pinecone-sync.py --corpus repos --repo FireHazmat
    python3.11 tools/pinecone-sync.py --dry-run             # list what would be sent

Reads the Pinecone API key from macOS Keychain entry (service=pinecone-api-key).
Embeds via Pinecone-hosted multilingual-e5-large.
State file: <vault>/tools/.pinecone-sync-state.json — tracks last-synced mtime per file, keyed by `<corpus>:<rel_path>`.
Legacy `<repo>/<path>` keys (pre-2026-04-17) continue to work; the sync will migrate them to `repos:<repo>/<path>` on next write.
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
RAW_UPLOADS = VAULT / "raw" / "uploads"
WIKI_DIR = VAULT / "wiki"
STATE_FILE = Path(__file__).resolve().parent / ".pinecone-sync-state.json"
INDEX_NAME = "openscaffold"

# Namespaces — one per corpus.
NS_REPOS = "repos"
NS_WIKI = "wiki"
NS_UPLOADS = "uploads"

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


# ---------- corpus iterators ----------
# Each yields (rel_path_for_state_key, metadata_dict, path_object)
# rel_path is the identity key (stable across runs); metadata carries corpus-specific tags.

def iter_repo_files(repo_filter: str | None):
    for repo_dir in sorted(RAW_REPOS.iterdir()):
        if not repo_dir.is_dir():
            continue
        if repo_filter and repo_dir.name != repo_filter:
            continue
        for path in repo_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            rel = path.relative_to(RAW_REPOS / repo_dir.name).as_posix()
            yield (
                f"{repo_dir.name}/{rel}",
                {"repo": repo_dir.name, "path": rel, "ext": path.suffix.lower()},
                path,
            )


def iter_wiki_files():
    # Wiki pages under wiki/** plus the vault's CLAUDE.md and README.md which are first-class context.
    extras = [VAULT / "CLAUDE.md", VAULT / "README.md"]
    for extra in extras:
        if extra.exists() and extra.is_file():
            yield (
                f"_root/{extra.name}",
                {"scope": "root", "path": extra.name, "ext": extra.suffix.lower()},
                extra,
            )
    for path in WIKI_DIR.rglob("*.md"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(WIKI_DIR).as_posix()
        # Bucket for filtering (entities/apps/concepts/synthesis/sources/…)
        bucket = rel.split("/", 1)[0] if "/" in rel else "root"
        yield (
            rel,
            {"scope": "wiki", "bucket": bucket, "path": rel, "ext": ".md"},
            path,
        )


def iter_upload_files():
    if not RAW_UPLOADS.exists():
        return
    for path in RAW_UPLOADS.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(RAW_UPLOADS).as_posix()
        yield (
            rel,
            {"scope": "uploads", "path": rel, "ext": path.suffix.lower()},
            path,
        )


def iter_corpus(name: str, repo_filter: str | None):
    if name == "repos":
        yield from iter_repo_files(repo_filter)
    elif name == "wiki":
        yield from iter_wiki_files()
    elif name == "uploads":
        yield from iter_upload_files()
    else:
        raise ValueError(f"unknown corpus: {name}")


def make_record(corpus: str, rel_id: str, chunk_idx: int, chunk: str, meta: dict) -> dict:
    rec_id = hashlib.sha1(f"{corpus}|{rel_id}|{chunk_idx}".encode()).hexdigest()
    rec = {
        "_id": rec_id,
        "chunk_text": chunk,
        "corpus": corpus,
        "chunk_index": chunk_idx,
    }
    rec.update(meta)
    return rec


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
            raw = json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
        # Legacy migration: keys without a `<corpus>:` prefix are from the old repo-only
        # format (`<repo>/<path>`); move them under the `repos:` prefix so they keep working.
        migrated = {}
        for k, v in raw.items():
            if ":" in k and k.split(":", 1)[0] in {"repos", "wiki", "uploads"}:
                migrated[k] = v
            else:
                migrated[f"repos:{k}"] = v
        return migrated
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def sync_corpus(name: str, namespace: str, index, state: dict, new_state: dict,
                repo_filter: str | None, args, token_window: deque) -> tuple[int, int, int, int]:
    """Sync one corpus. Returns (files, chunks, skipped, unchanged)."""
    batch = []
    files = 0
    chunks_total = 0
    skipped = 0
    unchanged = 0

    for rel_id, meta, path in iter_corpus(name, repo_filter):
        state_key = f"{name}:{rel_id}"
        mtime = path.stat().st_mtime
        if args.changed_only and state.get(state_key) == mtime:
            unchanged += 1
            continue

        text = read_file_text(path)
        if text is None or not text.strip():
            skipped += 1
            continue
        files += 1
        for i, chunk in enumerate(chunk_text(text)):
            batch.append(make_record(name, rel_id, i, chunk, meta))
            chunks_total += 1
            if len(batch) >= BATCH_SIZE:
                upsert_with_rate_limit(index, namespace, batch, token_window, args.dry_run)
                action = "would upsert" if args.dry_run else "upserted"
                print(f"  [{name}] {action} batch ({len(batch)})  total chunks: {chunks_total}  files: {files}")
                batch = []
        new_state[state_key] = mtime

    if batch:
        upsert_with_rate_limit(index, namespace, batch, token_window, args.dry_run)
        action = "would upsert" if args.dry_run else "upserted"
        print(f"  [{name}] {action} final batch ({len(batch)})")

    return files, chunks_total, skipped, unchanged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--corpus", choices=["all", "repos", "wiki", "uploads"], default="all",
                        help="which corpus to sync (default: all)")
    parser.add_argument("--repo", help="only sync this repo (only relevant for --corpus repos)")
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

    corpora_to_run = ["repos", "wiki", "uploads"] if args.corpus == "all" else [args.corpus]

    if args.seed_state:
        seeded = {}
        for name in corpora_to_run:
            for rel_id, _meta, path in iter_corpus(name, args.repo if name == "repos" else None):
                seeded[f"{name}:{rel_id}"] = path.stat().st_mtime
        save_state(seeded)
        print(f"seeded state with {len(seeded)} entries across {corpora_to_run}: {STATE_FILE}")
        return

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index(INDEX_NAME)

    state = load_state() if args.changed_only else {}
    new_state = dict(state)

    ns_for = {"repos": NS_REPOS, "wiki": NS_WIKI, "uploads": NS_UPLOADS}
    token_window: deque = deque()

    totals = {"files": 0, "chunks": 0, "skipped": 0, "unchanged": 0}
    per_corpus: dict[str, dict] = {}

    for name in corpora_to_run:
        print(f"\n=== corpus: {name} (namespace={ns_for[name]}) ===")
        repo_filter = args.repo if name == "repos" else None
        files, chunks_total, skipped, unchanged = sync_corpus(
            name, ns_for[name], index, state, new_state, repo_filter, args, token_window
        )
        per_corpus[name] = {"files": files, "chunks": chunks_total, "skipped": skipped, "unchanged": unchanged}
        totals["files"] += files
        totals["chunks"] += chunks_total
        totals["skipped"] += skipped
        totals["unchanged"] += unchanged

    if not args.dry_run:
        save_state(new_state)

    print("\n=== summary ===")
    for name, c in per_corpus.items():
        print(f"  {name:9s} files: {c['files']:5d}  chunks: {c['chunks']:6d}  skipped: {c['skipped']:4d}  unchanged: {c['unchanged']:5d}")
    print(f"  TOTAL     files: {totals['files']:5d}  chunks: {totals['chunks']:6d}  skipped: {totals['skipped']:4d}  unchanged: {totals['unchanged']:5d}  dry_run: {args.dry_run}")


if __name__ == "__main__":
    main()
