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

## Hub vault + LimitlessStack sync contract (added 2026-04-29)

**This repo's `tools/` and `skills/` MUST always match the deployed copies in active vaults (the Hub vault at `/Users/matthewlavin/Claude code antigravity/obsidian` is the primary one) and `~/.claude/skills/`.** Drift in either direction is a hard failure of the protocol's "single source of truth" property.

Background: Fixes sometimes get made in the Hub vault during active work (hot-fixing real bugs in the running system). Those fixes MUST be back-ported to this repo before session close — otherwise `install.sh` will deploy the OLD version to any new project, baking in bugs we've already fixed. Observed 2026-04-29: 174 lines of cmd_replace / routing / coverage fixes lived in the Hub vault for a session before the gap was noticed.

**Mechanical enforcement lives in `tools/limitless-preflight.sh`** — the "Limitless Stack canonical sync" check diffs every active vault's `tools/` and `~/.claude/skills/` against this repo's `tools/` and `skills/`. Any drift fires a ⚠ on the next session's Roll Call with the exact `cp` command. The check uses `$LIMITLESS_STACK_HOME` (default `/Users/matthewlavin/LimitlessStack` — i.e., this repo's local clone path).

**When you edit anything in this repo's `tools/` or `skills/`:**
1. Mirror the same change to the Hub vault's `tools/` (and `~/.claude/skills/<skill>/SKILL.md` for skills)
2. Run the Hub vault's `tools/limitless-preflight.sh` — the sync check should pass
3. Commit + push BOTH repos in the same logical change (separate commits OK, but in the same session)

**When you edit anything in the Hub vault's `tools/`:**
Same in reverse — back-port to this repo's `tools/`, run preflight, commit + push both.

See [[synthesis/claude-anti-patterns]] in the Hub vault wiki, entry #14, for the anti-pattern this contract prevents.
