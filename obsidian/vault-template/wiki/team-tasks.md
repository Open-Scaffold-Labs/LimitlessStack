---
tasks_audited: __TODAY__
---

# Tasks

What is open and what shipped. **Newest first:** new work goes to the TOP of Active; when it
ships, tick it and move it to the TOP of Archive. The session write-up belongs in `log.md`, not here.

## Active

### __TODAY__ — finish setting up this stack

- [ ] Fill in every `[YOUR …]` marker in `CLAUDE.md` (name, domain, working rules, notes)
- [ ] `notebooklm login`, create your default + reminder notebooks, put their IDs in `.limitless-project.py`
- [ ] Seed the notebooks: `python3.11 tools/notebooklm-wiki-refresh.py --seed`, then a normal refresh
- [ ] Write your own `wiki/overview.md` (and give it real dates)
- [ ] Optional: Pinecone — your index, your key in the Keychain, `"pinecone"` in `CHECKS`
- [ ] Optional: turn on the nightly self-heal job (the installer printed the two commands)
- [ ] Run Roll Call until it reports READY or only the WARNs you've chosen to accept

## Archive
