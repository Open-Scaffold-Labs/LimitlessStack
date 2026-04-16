# OpenScaffold Memory System — Setup Guide

**Paste this entire document into a Claude Code or Cowork session and say "Set this up for me."** The session will replicate the memory system Matt Lavin built on 2026-04-14. Target platform: macOS with an existing Homebrew install. Estimated wall time: ~30 minutes once accounts are in hand.

---

## What you're building

A **four-tool knowledge system** around OpenScaffold:

| Tool | Role | Where it lives |
|---|---|---|
| `CLAUDE.md` | Identity / rules / voice | Vault root + per-repo |
| Obsidian | Workshop — structured knowledge and graph | Local vault folder |
| NotebookLM | Research desk — topic notebooks over curated sources | cloud (google.com/notebooklm) |
| Pinecone | Warehouse — semantic search over raw corpus | cloud (pinecone.io) |

Each tool is bad at the others' jobs. This setup makes them work together in one loop: ingest → structure → index → search.

---

## Prerequisites (you ensure these exist before running)

### Accounts
- **GitHub** with access to the org whose repos you'll index. Create a Personal Access Token with `repo` scope if you don't already have CLI auth.
- **Pinecone** (free Starter tier is fine). Grab the API key from the Pinecone console.
- **Google account with NotebookLM access** — you'll need to be logged into it in Chrome.

### Software on the Mac
- **Homebrew** (`brew --version`)
- **Python 3.11** (`brew install python@3.11`)
- **Node.js** (`brew install node` — needed only if you want to build the .docx handoff doc)
- **Obsidian** (`brew install --cask obsidian`)
- **gh CLI** (`brew install gh`) — then `gh auth login` → HTTPS → web browser flow
- **Chrome** with the [Claude for Chrome](https://claude.ai/chrome) extension installed and connected

### Python libraries (will install in Step 4)
```
pip install pinecone python-docx pdfplumber "notebooklm-py[browser]"
playwright install chromium
```

---

## Step 1 — Create the vault

Pick a folder path. Matt's is `~/Claude code antigravity/obsidian/` (trailing space intentional). For Dale you might use `~/OpenScaffold-Vault/` (no space — simpler).

```bash
VAULT=~/OpenScaffold-Vault
mkdir -p "$VAULT"/{raw/openscaffold-repos,raw/assets,wiki/{entities,apps,concepts,sources,synthesis},tools,deliverables}
```

---

## Step 2 — Install the schema (`CLAUDE.md`)

Create `$VAULT/CLAUDE.md` with the content below. This is the operating manual that every session reads on start.

```markdown
# LLM Wiki — Schema & Operating Manual

## Purpose

This vault implements the LLM Wiki pattern: you curate sources and ask questions; the LLM reads sources and maintains a structured, interlinked markdown knowledge base that compounds over time.

**Domain**: Open Scaffold Labs — founder Dale Raaen. Track architecture, apps in the ecosystem, people, concepts, decisions.

**Default lens when reading a new source**: *how does this change my picture of the OpenScaffold architecture or any specific app?*

## Architecture (three layers)

1. `raw/` — immutable source documents. LLM reads, never modifies.
2. `wiki/` — LLM-owned markdown pages (entities, apps, concepts, sources, synthesis, plus `index.md` + `log.md` + `overview.md`).
3. This file — the schema, co-evolves with the human.

## Directory conventions

```
/
├── CLAUDE.md
├── README.md
├── raw/
│   └── openscaffold-repos/   # cloned repos
├── wiki/
│   ├── index.md              # catalog
│   ├── log.md                # chronological log
│   ├── overview.md           # top-level synthesis
│   ├── entities/             # people, orgs
│   ├── apps/                 # one page per app
│   ├── concepts/             # one page per pattern/term
│   ├── sources/              # one summary per raw source
│   └── synthesis/            # diagrams, filed query answers, lint reports
└── tools/
    ├── pinecone-sync.py
    └── pinecone-search.py
```

## Page conventions

- Filenames: kebab-case, `.md`.
- Links: Obsidian wiki-links `[[page-name]]`.
- Frontmatter (YAML) on every page: `type`, `created`, `updated`, `tags`, `source_count`, `sources`.
- Citations: inline, pointing to source summary pages.
- Never reproduce more than ~15 words verbatim from a source.

## Core operations

**Ingest** — when a new source lands in `raw/`:
1. Read the source fully.
2. Create `wiki/sources/<slug>.md` with frontmatter, summary, key points (with wiki-links), extracted claims.
3. Update/create entity/concept/app pages. Flag contradictions with a `> [!warning]` callout.
4. Update `wiki/index.md`.
5. Append to `wiki/log.md` with format `## [YYYY-MM-DD] <op> | <label>`.

**Query** — when the human asks a question:
1. Read `wiki/index.md` first.
2. Drill into relevant pages; follow wiki-links.
3. If the wiki is thin on the topic, run Pinecone semantic search before grepping raw/:
   ```
   python3.11 tools/pinecone-search.py "the question" --top 5
   ```
4. For deep research with curated sources, query the relevant NotebookLM notebook via Claude in Chrome.
5. If the answer is substantive, file it as `wiki/synthesis/<slug>.md` and append a `query` log entry.

**Lint** — periodic health check: contradictions, stale claims, orphans, missing pages, broken links, coverage gaps, index drift. Write to `wiki/synthesis/lint-YYYY-MM-DD.md`.

## Using the four-tool memory system

1. Read `wiki/index.md` first.
2. Thin wiki coverage → `python3.11 tools/pinecone-search.py "..." --top 5`.
3. Deep research → NotebookLM topic notebook via Claude in Chrome (notebook IDs in `wiki/concepts/notebooklm-workflow.md`).
4. Substantive answers → file to `wiki/synthesis/`.
5. New source → also run `python3.11 tools/pinecone-sync.py --changed-only`.

## Working style (standing rules)

- Act on authorized tasks — cloning repos, installing CLI tools, running scheduled jobs, driving the desktop to accomplish the stated task. Don't re-ask for approvals already given.
- Be deliberate, not reckless. Before any action that changes state:
  1. Confirm exactly what the command does and what it touches.
  2. Prefer reversible actions. If destructive (delete, force-push, drop-table), stop and ask.
  3. Run narrowly — one file, one repo, one path.
  4. Verify the result. If unexpected, stop and report; do not paper over.
  5. Ask when uncertain. Uncertainty is not an excuse to gamble.
- If you break something, it's on you. Trust raises the bar on your care, not lowers it.
- Physical OS prompts (Keychain password dialogs) are the human's to click.
- Hard safety rails always: never push/commit without asking, never move money, never exfiltrate credentials.

## Guardrails

- Never edit files in `raw/`.
- Never reproduce more than ~15 words verbatim.
- When uncertain whether a claim is supported, say so — don't fabricate cross-references.
- Contradictions: flag explicitly with `> [!warning]`, never silently overwrite.

## Evolution

Edit this file when a convention needs updating. Append a `schema` entry to the log.
```

Also create `$VAULT/wiki/index.md`, `$VAULT/wiki/log.md`, and `$VAULT/wiki/overview.md` with minimal starter content (one "Overview" heading each; the LLM will populate as sources arrive).

---

## Step 3 — Clone the repos you care about

```bash
cd "$VAULT/raw/openscaffold-repos"
gh repo clone Open-Scaffold-Labs/openscaffold-core
gh repo clone Open-Scaffold-Labs/open-scaffold-docs
gh repo clone Open-Scaffold-Labs/OpenFirehouse
gh repo clone Open-Scaffold-Labs/FireHazmat
# add any others you want indexed
```

Keep the clone list focused. The Pinecone free tier supports 100,000 vectors per index; each repo adds thousands. Start with the repos you'll query against most.

---

## Step 4 — Install Python deps and set up Pinecone

```bash
pip3.11 install --break-system-packages pinecone python-docx pdfplumber "notebooklm-py[browser]"
playwright install chromium
```

Save your Pinecone API key to macOS Keychain (runs interactively — you'll be prompted to paste the key, hidden input):

```bash
security add-generic-password -a pinecone -s pinecone-api-key -U -w
```

Then create the `openscaffold` index (1024-dim, cosine, us-east-1, hosted embedding):

```bash
PINECONE_API_KEY=$(security find-generic-password -s pinecone-api-key -w) python3.11 - << 'EOF'
import os, time
from pinecone import Pinecone
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
if not pc.has_index("openscaffold"):
    pc.create_index_for_model(
        name="openscaffold",
        cloud="aws", region="us-east-1",
        embed={"model": "multilingual-e5-large", "field_map": {"text": "chunk_text"}},
    )
    while not pc.describe_index("openscaffold").status.ready:
        time.sleep(2)
print("ready:", pc.describe_index("openscaffold").host)
EOF
```

---

## Step 5 — Install the sync + search tools

Create `$VAULT/tools/pinecone-sync.py` and `$VAULT/tools/pinecone-search.py` with the scripts provided at the bottom of this guide. They read the API key from Keychain, chunk files, handle rate-limits, and support `--changed-only` and `--repo NAME` flags.

---

## Step 6 — First sync

```bash
cd "$VAULT"
python3.11 tools/pinecone-sync.py --dry-run   # see what will be sent
python3.11 tools/pinecone-sync.py              # actual sync (~2 min per 1000 chunks on free tier)
```

Verify it worked:

```bash
python3.11 tools/pinecone-search.py "JWT refresh shared users table"
python3.11 tools/pinecone-search.py "ERG Table 3 hazmat" --top 3
```

You should see real file paths and score values ≥0.8 for good matches.

---

## Step 7 — NotebookLM topic notebooks

**Option A (recommended) — drive it through Claude in Chrome:**
1. Make sure the Claude for Chrome extension is connected and you're signed into NotebookLM in your browser.
2. Ask Claude: "Create three NotebookLM notebooks: 'OpenScaffold Wiki' (upload every file under wiki/), 'OpenScaffold Architecture' (upload raw/openscaffold-repos/open-scaffold-docs/architecture/*.docx plus the per-repo CLAUDE.md files), and 'OpenScaffold Business' (upload raw/openscaffold-repos/open-scaffold-docs/business/ and white-papers/)."
3. Note the three notebook IDs that come back. Record them in `wiki/concepts/notebooklm-workflow.md`.

**Option B — notebooklm-py CLI:**
```bash
# One-time setup
pip install "notebooklm-py[browser]"
playwright install chromium
notebooklm login           # opens browser — complete Google sign-in, press Enter in terminal
notebooklm skill install   # installs Claude Code skill (v0.3.4)

# Verify auth works
notebooklm auth check --test

# Create notebook and upload sources
notebooklm create "OpenScaffold Architecture"
# Capture the notebook ID from the output, then upload sources:
notebooklm use <notebook-id>
for f in raw/openscaffold-repos/open-scaffold-docs/architecture/*; do
  notebooklm source add "$f"
done
```

If auth expires later, just re-run `notebooklm login` to refresh. No manual cookie extraction needed.

---

## Step 8 — Schedule the nightly sync

If you're using Cowork with the `schedule` skill, ask Claude: "Schedule a task named `pinecone-nightly-sync` to run at 3:10 AM daily." Prompt content (self-contained so the scheduled run has full context):

> Run an unattended nightly Pinecone --changed-only sync for the OpenScaffold vault.
>
> Vault: `~/OpenScaffold-Vault/` (your actual path).
> Pinecone API key: macOS Keychain, service `pinecone-api-key`.
> Sync script: `<vault>/tools/pinecone-sync.py` (reads its own key).
>
> Steps:
> 1. `git pull` inside each subdir of `<vault>/raw/openscaffold-repos/*/`. Tolerate per-repo failures.
> 2. `cd <vault> && python3.11 tools/pinecone-sync.py --changed-only`
> 3. If files synced > 0, append `## [YYYY-MM-DD] schema | nightly Pinecone sync — <files> files / <chunks> chunks` to `<vault>/wiki/log.md`.
> 4. Report new commits per repo, sync count, and any errors.
>
> Do not push commits. Do not modify raw/. Log-line append is the only write.

If you're not on Cowork, use `crontab -e`:
```
10 3 * * * cd ~/OpenScaffold-Vault && python3.11 tools/pinecone-sync.py --changed-only >> /tmp/pinecone-nightly.log 2>&1
```

---

## Daily usage, once it's all live

- **New source lands?** Drop it in `raw/openscaffold-repos/<repo>/<path>` (or `git pull`), then run `python3.11 tools/pinecone-sync.py --changed-only` to update the index. Ask Claude to ingest it into the wiki.
- **Question you've asked before?** Read `wiki/index.md`, follow the links, done.
- **Question about code across many repos?** `python3.11 tools/pinecone-search.py "..."`. Feed the top hits to Claude for synthesis.
- **Deep topic you'll keep coming back to?** Create a new NotebookLM notebook for it; don't clutter the general ones.
- **Monthly?** Ask Claude to run a lint pass: "Run a lint pass and write the report."

---

## Reference — `tools/pinecone-sync.py`

```python
#!/usr/bin/env python3.11
"""
Sync the raw/ corpus into the Pinecone 'openscaffold' index.

Usage:
    python3.11 tools/pinecone-sync.py                  # full sync
    python3.11 tools/pinecone-sync.py --changed-only   # only modified files
    python3.11 tools/pinecone-sync.py --dry-run
    python3.11 tools/pinecone-sync.py --repo NAME      # one repo only
    python3.11 tools/pinecone-sync.py --seed-state     # record current mtimes without uploading
    python3.11 tools/pinecone-sync.py --reset-state

Reads PINECONE_API_KEY from macOS Keychain (service=pinecone-api-key).
State file at tools/.pinecone-sync-state.json tracks last-synced mtime per file.
"""
import argparse, hashlib, json, os, subprocess, sys, time
from collections import deque
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
RAW_REPOS = VAULT / "raw" / "openscaffold-repos"
STATE_FILE = Path(__file__).resolve().parent / ".pinecone-sync-state.json"
INDEX_NAME = "openscaffold"
NAMESPACE = "repos"
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
BATCH_SIZE = 96
CHARS_PER_TOKEN = 4
TOKENS_PER_MINUTE_LIMIT = 200_000
SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", ".expo", "ios",
             "android", ".vercel", "__pycache__", ".pytest_cache", "coverage"}
TEXT_EXTS = {".md", ".txt", ".js", ".jsx", ".ts", ".tsx", ".py", ".json", ".yml",
             ".yaml", ".toml", ".css", ".html", ".sql", ".sh", ".env.example"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
MAX_FILE_BYTES = 2_000_000


def get_api_key():
    return subprocess.run(
        ["security", "find-generic-password", "-s", "pinecone-api-key", "-w"],
        capture_output=True, text=True, check=True
    ).stdout.strip()


def read_file_text(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    ext = path.suffix.lower()
    if ext in TEXT_EXTS or path.name in {"README", "LICENSE", "CHANGELOG", "Dockerfile"}:
        try: return path.read_text(encoding="utf-8", errors="ignore")
        except: return None
    if ext in DOCX_EXTS:
        try:
            from docx import Document
            return "\n\n".join(p.text for p in Document(path).paragraphs if p.text.strip())
        except: return None
    if ext in PDF_EXTS:
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n\n".join(p.extract_text() or "" for p in pdf.pages)
        except: return None
    return None


def chunk_text(text):
    text = text.strip()
    if not text: return
    i = 0
    while i < len(text):
        yield text[i:i+CHUNK_CHARS]
        if i + CHUNK_CHARS >= len(text): break
        i += CHUNK_CHARS - CHUNK_OVERLAP


def iter_files(root, repo_filter):
    for repo_dir in sorted(root.iterdir()):
        if not repo_dir.is_dir(): continue
        if repo_filter and repo_dir.name != repo_filter: continue
        for path in repo_dir.rglob("*"):
            if not path.is_file(): continue
            if any(part in SKIP_DIRS for part in path.parts): continue
            yield repo_dir.name, path


def make_record(repo, path, chunk_idx, chunk):
    rel = path.relative_to(RAW_REPOS / repo).as_posix()
    rec_id = hashlib.sha1(f"{repo}|{rel}|{chunk_idx}".encode()).hexdigest()
    return {"_id": rec_id, "chunk_text": chunk, "repo": repo, "path": rel,
            "ext": path.suffix.lower(), "chunk_index": chunk_idx}


def upsert_with_rate_limit(index, ns, batch, window, dry_run):
    batch_tokens = sum(len(r["chunk_text"]) for r in batch) // CHARS_PER_TOKEN
    now = time.time()
    while window and now - window[0][0] > 60: window.popleft()
    used = sum(t for _, t in window)
    if used + batch_tokens > TOKENS_PER_MINUTE_LIMIT and window:
        sleep_for = 60 - (now - window[0][0]) + 0.5
        if sleep_for > 0:
            print(f"  rate-limit sleep {sleep_for:.1f}s")
            time.sleep(sleep_for)
            now = time.time()
            while window and now - window[0][0] > 60: window.popleft()
    if dry_run:
        window.append((now, batch_tokens)); return
    delay = 5
    for _ in range(6):
        try:
            index.upsert_records(ns, batch)
            window.append((time.time(), batch_tokens)); return
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"  429, sleep {delay}s"); time.sleep(delay); delay = min(delay*2, 60); continue
            raise
    raise RuntimeError("Exceeded 429 retries")


def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: return {}
    return {}


def save_state(s): STATE_FILE.write_text(json.dumps(s, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo")
    p.add_argument("--changed-only", action="store_true")
    p.add_argument("--reset-state", action="store_true")
    p.add_argument("--seed-state", action="store_true")
    args = p.parse_args()

    if args.reset_state:
        if STATE_FILE.exists(): STATE_FILE.unlink()
        print("state cleared"); return
    if args.seed_state:
        s = {f"{r}/{pth.relative_to(RAW_REPOS / r).as_posix()}": pth.stat().st_mtime
             for r, pth in iter_files(RAW_REPOS, args.repo)}
        save_state(s); print(f"seeded {len(s)} files"); return

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index(INDEX_NAME)
    state = load_state() if args.changed_only else {}
    new_state = dict(state)
    batch, files, chunks_total, skipped, unchanged = [], 0, 0, 0, 0
    window = deque()

    for repo, path in iter_files(RAW_REPOS, args.repo):
        key = f"{repo}/{path.relative_to(RAW_REPOS / repo).as_posix()}"
        mtime = path.stat().st_mtime
        if args.changed_only and state.get(key) == mtime:
            unchanged += 1; continue
        text = read_file_text(path)
        if text is None or not text.strip():
            skipped += 1; continue
        files += 1
        for i, chunk in enumerate(chunk_text(text)):
            batch.append(make_record(repo, path, i, chunk))
            chunks_total += 1
            if len(batch) >= BATCH_SIZE:
                upsert_with_rate_limit(index, NAMESPACE, batch, window, args.dry_run)
                action = "would upsert" if args.dry_run else "upserted"
                print(f"  {action} batch ({len(batch)})  chunks: {chunks_total}  files: {files}")
                batch = []
        new_state[key] = mtime
    if batch:
        upsert_with_rate_limit(index, NAMESPACE, batch, window, args.dry_run)
        action = "would upsert" if args.dry_run else "upserted"
        print(f"  {action} final ({len(batch)})")
    if not args.dry_run: save_state(new_state)
    print(f"\nDONE  files: {files}  chunks: {chunks_total}  skipped: {skipped}  unchanged: {unchanged}  dry_run: {args.dry_run}")


if __name__ == "__main__":
    main()
```

## Reference — `tools/pinecone-search.py`

```python
#!/usr/bin/env python3.11
"""
Semantic search over the OpenScaffold Pinecone index.

Usage:
    python3.11 tools/pinecone-search.py "where do we handle JWT refresh"
    python3.11 tools/pinecone-search.py "..." --top 3 --repo FireHazmat
"""
import argparse, subprocess


def get_api_key():
    return subprocess.run(
        ["security", "find-generic-password", "-s", "pinecone-api-key", "-w"],
        capture_output=True, text=True, check=True
    ).stdout.strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--repo")
    p.add_argument("--namespace", default="repos")
    args = p.parse_args()

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index("openscaffold")
    kwargs = {
        "namespace": args.namespace,
        "query": {"top_k": args.top, "inputs": {"text": args.query}},
        "fields": ["repo", "path", "chunk_index", "chunk_text"],
    }
    if args.repo:
        kwargs["query"]["filter"] = {"repo": {"$eq": args.repo}}
    results = index.search(**kwargs)

    print(f"\nQuery: {args.query}")
    if args.repo: print(f"Filter: repo={args.repo}")
    print(f"Top {args.top} hits:\n")
    for hit in results.result.hits:
        f = hit.fields
        score = hit._score if hasattr(hit, "_score") else hit.score
        snippet = (f.get("chunk_text") or "")[:200].replace("\n", " ")
        print(f"  [{score:.3f}]  {f['repo']}/{f['path']}  (chunk {f.get('chunk_index')})")
        print(f"           {snippet}…\n")


if __name__ == "__main__":
    main()
```

---

## Troubleshooting

- **Pinecone sync hits 429 Too Many Requests** — the script handles this by backing off; first syncs take ~20 minutes on the free tier's 250k tokens/minute limit.
- **NotebookLM auth expired** — run `notebooklm login` to re-authenticate via browser. Verify with `notebooklm auth check --test`.
- **"Keychain item not found"** — re-run `security add-generic-password -a pinecone -s pinecone-api-key -U -w` and paste the key into the prompt.
- **Python says `import docx` or `import pinecone` not found** — make sure you used `pip3.11 install --break-system-packages ...` and not plain `pip`. The system Python ignores pip by default on recent macOS.
- **`gh repo clone` auth error** — `gh auth login` → GitHub.com → HTTPS → Login with a web browser → follow the device-code flow.

---

## Success criteria

Your setup is working when all four are true:

1. **Obsidian** opens the vault and the graph view shows `CLAUDE.md` linked to `wiki/` content.
2. **Pinecone** `python3.11 tools/pinecone-search.py "any question about your code"` returns results with file paths.
3. **NotebookLM** has at least one topic notebook with your architecture docs as sources, and you can query it via Claude in Chrome.
4. **A nightly scheduled task** is running `pinecone-sync.py --changed-only` and appending to the log.

At that point, any new Claude session can read `CLAUDE.md`, browse the wiki, search Pinecone, and query NotebookLM — and answer OpenScaffold questions with citations backed by your actual code and docs.

Welcome to the compounding-knowledge club.
