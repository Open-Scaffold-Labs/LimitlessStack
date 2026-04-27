# LimitlessStack — Repo Rules

This repo contains the Limitless Stack — the operating protocol for Open Scaffold Labs. It dogfoods its own protocol.

## Before any work

1. Invoke the `roll-call` skill (mechanically verifies all seven tools — see `skills/roll-call/SKILL.md`).
2. Run `tools/session-bootstrap.sh` if working in a vault context.
3. Read `skills/limitless-stack/SKILL.md` — that's the protocol this repo defines. Know it. The "Mandatory First Action" + "End-of-Session Checklist" sections in SKILL.md are the canonical session lifecycle.

## What lives here

- `skills/limitless-stack/` — The installable protocol (SKILL.md). This is the primary deliverable.
- `skills/notebooklm/` — The NotebookLM skill (bundled from notebooklm-py). Full CLI API.
- `claude-md/` — CLAUDE.md templates for vaults and repos (including self-healing trust anchor config).
- `obsidian/` — Vault template with the wiki directory skeleton.
- `pinecone/` — Sync and search scripts.
- `notebooklm/` — Wiki refresh tooling.
- `self-heal/` — Self-healing pipeline: canonical templates (workflow, agent script, setup guide), security model, rollout plan.
- `hub-workspace/` — Integration spec for the Hub's agent-runtime surface.
- `paperclip/` — Integration spec.
- `docs/` — Setup guide and documentation.
- `.claude-plugin/` — Plugin packaging for Claude Code distribution.

## Rules

- **Don't commit without asking.** This repo defines protocol that many agents depend on. Changes need review.
- **Don't push without asking.** Same reason.
- **Keep the SKILL.md under 500 lines.** If it's growing past that, move details into component READMEs and reference them.
- **Update the version** in `skills/limitless-stack/SKILL.md` frontmatter, `plugin.json`, and `marketplace.json` together. They must stay in sync.
- **Test changes against a real vault** before pushing. The protocol should work, not just read well.
