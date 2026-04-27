# Pinecone — Semantic Memory

Pinecone provides full-text semantic recall across all OpenScaffold repos and documents. It's tool #2 in the four-tool lookup order — use it when the wiki is thin on a topic.

## Role in the Stack

Pinecone indexes the raw corpus (cloned repos, docs, transcripts) into a searchable vector database. When you ask a question and the wiki doesn't have enough, Pinecone surfaces the most relevant code and docs across all repos instantly. As the ecosystem grows to 100 apps, Pinecone is what makes it possible to search across all of them in a single query.

## Role in Self-Healing

Pinecone powers the **cross-application pattern library** — the mechanism that makes the self-healing pipeline smarter over time:

- Diagnostic outputs from bug reports are indexed alongside code, so a search for a bug pattern in one app can surface identical patterns already fixed in another
- When a pattern is detected across multiple apps (e.g. missing table prefixes, wrong route registration order), it gets filed into the wiki as a synthesis page
- Those patterns then get folded back into each app's CLAUDE.md as "known patterns," improving future diagnostic accuracy across the entire fleet

This feedback loop — bugs → diagnoses → Pinecone → wiki → CLAUDE.md → better diagnoses — is how the system compounds.

## What's in this folder

- **`pinecone-sync.py`** — Chunks and upserts files from `raw/openscaffold-repos/` into the Pinecone index. Handles rate limits, tracks sync state, supports incremental updates.
- **`pinecone-search.py`** — Semantic search across the index. Returns ranked results with file paths, scores, and text snippets.

## Index configuration

| Setting | Value |
|---|---|
| Index name | `openscaffold` |
| Namespace | `repos` |
| Embedding model | `multilingual-e5-large` |
| Dimensions | 1024 |
| Metric | cosine |
| Region | us-east-1 (AWS) |

## Usage

```bash
# Search
python3.11 tools/pinecone-search.py "where do we handle JWT refresh" --top 5
python3.11 tools/pinecone-search.py "ERG Table 3 hazmat" --repo FireHazmat --top 3

# Search for cross-app patterns
python3.11 tools/pinecone-search.py "missing table prefix bug" --top 10

# Sync (incremental — only changed files)
python3.11 tools/pinecone-sync.py --changed-only

# Sync (single repo)
python3.11 tools/pinecone-sync.py --repo OpenFirehouse

# Sync (dry run)
python3.11 tools/pinecone-sync.py --dry-run
```

## Setup

```bash
pip3.11 install --break-system-packages pinecone
# Store API key in macOS Keychain
security add-generic-password -a pinecone -s pinecone-api-key -U -w
```

Both scripts read the API key from Keychain automatically.

## Nightly sync

A scheduled task runs `pinecone-sync.py --changed-only` at 3:10 AM daily. It pulls latest commits from each repo, syncs changed files, and appends a log entry to `wiki/log.md`.

## Integration points

- **Obsidian** — Pinecone indexes `raw/` content; search results get cited in wiki pages and filed as synthesis
- **CLAUDE.md** — The four-tool lookup order puts Pinecone at step #2. Cross-app patterns from Pinecone feed back into CLAUDE.md files.
- **NotebookLM** — Pinecone finds relevant files that can then be uploaded to NotebookLM notebooks for deeper analysis
- **Hub Workspace** — Agents running in Hub Workspace call Pinecone search scripts directly
- **Paperclip** — Paperclip can query Pinecone to inform ticket routing and prioritization
- **Self-healing** — Indexed diagnostic outputs power cross-app pattern detection; Pinecone search helps the diagnostic agent find related fixes in other repos
