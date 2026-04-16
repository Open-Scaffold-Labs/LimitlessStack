# NotebookLM — Research Desk

NotebookLM provides deep research across curated source collections. It's tool #3 in the four-tool lookup order — use it when you need to go deeper than what the wiki and Pinecone can surface.

## Role in the Stack

Each topic gets its own NotebookLM notebook with relevant documents uploaded as sources. NotebookLM excels at synthesizing across those sources — finding patterns, contradictions, and connections that semantic search alone might miss. It can also generate artifacts like podcasts, videos, reports, quizzes, and mind maps from the research.

For a 100-vertical platform, NotebookLM is where you do deep analysis on market segments, competitive landscapes, and architectural decisions that span multiple apps.

## Role in Self-Healing

NotebookLM supports the analytical side of the self-healing ecosystem:

- **Bug pattern research** — When Pinecone surfaces recurring bug patterns across apps, NotebookLM notebooks with curated diagnostic data enable deeper analysis of root causes and systemic issues
- **Architecture decisions** — Dale's self-healing architecture document and TAM analysis can be uploaded as sources to notebooks for deep research into rollout strategy, cost optimization, and feature prioritization
- **Vertical market research** — Each vertical's market data (business counts, ARPU, software penetration, competitive landscape) can be studied in dedicated notebooks to inform which apps get self-healing first

## What's in this folder

- **`notebooklm-wiki-refresh.py`** — Automates the workflow of refreshing NotebookLM notebooks with updated wiki content.

## The notebooklm-py CLI

The full NotebookLM API is handled by the `notebooklm-py` package and its companion Claude skill (installed via `notebooklm skill install`). That skill covers the complete CLI — creating notebooks, adding sources, generating artifacts, downloading results, error handling, and subagent patterns.

### Setup

```bash
pip install "notebooklm-py[browser]"
playwright install chromium
notebooklm login          # opens browser for Google sign-in
notebooklm skill install  # installs the Claude Code skill
notebooklm auth check --test
```

If auth expires, re-run `notebooklm login`. No manual cookie extraction needed.

### Quick reference

```bash
notebooklm list                          # list notebooks
notebooklm create "Topic Name"           # create a notebook
notebooklm use <notebook-id>             # set context
notebooklm source add ./file.pdf         # add a source
notebooklm ask "your question"           # chat with sources
notebooklm generate audio "instructions" # create a podcast
```

## Notebook IDs

Tracked in `wiki/concepts/notebooklm-workflow.md` inside the Obsidian vault. When creating new notebooks, record the ID there so other agents can find them.

## Integration points

- **Obsidian** — Wiki content can be uploaded as notebook sources; research results get filed back as synthesis pages
- **CLAUDE.md** — The four-tool lookup order puts NotebookLM at step #3
- **Pinecone** — Pinecone search surfaces relevant files that can be uploaded to notebooks
- **Antigravity** — Agents running in Antigravity query notebooks via the CLI
- **Paperclip** — Paperclip queries notebooks for research backing organizational decisions
- **Self-healing** — Bug pattern research, architecture analysis, vertical market research for rollout prioritization
