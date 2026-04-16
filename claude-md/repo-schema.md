# CLAUDE.md — Repo Schema Template

Copy this into your repo root as `CLAUDE.md` and customize. This file serves two purposes: it defines how agents behave in this repo, AND it acts as the trust anchor for the self-healing pipeline — both the diagnostic and repair agents receive it as their system prompt.

```markdown
# [App Name] — Agent Rules

## Before any work

Install the Limitless Stack skill if not already present:
```
/plugin install limitless-stack@limitless-stack
```

The skill teaches the full cross-cutting protocol (four-tool lookup, wiki maintenance, Pinecone search, NotebookLM research, self-healing pipeline). This file covers repo-specific rules only.

## What this app is

[Brief description: what vertical it serves, who the users are, what it does. The self-healing agent reads this to understand the domain.]

- **Vertical**: [e.g. Food Service & Hospitality]
- **NAICS**: [e.g. 72]
- **Users**: [e.g. Independent restaurant owners, 1-20 employees]
- **Stack**: React + Supabase + Vercel
- **Table prefix**: [e.g. `or_`]

## Repo-specific rules

- [Commit conventions]
- [Deployment targets]
- [Testing requirements — what `npm test` runs]
- [Any repo-specific patterns the agent should know]

## Known patterns and common pitfalls

These patterns help the self-healing agent diagnose bugs accurately. Update this section as the cross-application pattern library surfaces new patterns.

- [e.g. "All Supabase queries must use the table prefix. Missing prefix causes 'relation not found' errors."]
- [e.g. "Route registrations must be ordered specific-to-general. Wrong order causes wrong handler matching."]
- [e.g. "Factory functions in /server/src/factories/ require all arguments. Missing arguments cause silent null returns."]

## Self-healing configuration

- **Phase**: [none | diagnostic | full]
- **Self-heal enabled**: [true | false]
- **Bug report table**: [e.g. `or_bug_reports`]
- **Canonical files present**: [checklist]
  - [ ] `/.github/workflows/self-heal.yml`
  - [ ] `/scripts/self-heal-agent.js`
  - [ ] `/server/src/routes/debug-agent.js`
  - [ ] `/client/src/components/BugReporter.jsx`
  - [ ] `/client/src/pages/DebugReportsPage.jsx`
  - [ ] `/SELF-HEAL-SETUP.md`

## Dependencies

- [Key dependencies and why they exist]

## Don't

- Don't push without asking.
- Don't commit without asking.
- Don't edit files in `.github/`, `.env`, `node_modules/`, or `package-lock.json`.
- [Any repo-specific prohibitions]
```
