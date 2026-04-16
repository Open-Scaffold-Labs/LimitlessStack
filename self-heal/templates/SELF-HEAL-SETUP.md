# Self-Heal Setup Guide

This document describes how to configure the self-healing pipeline for this application.

## Prerequisites

- Application deployed on Vercel with Supabase backend
- GitHub repository under Open-Scaffold-Labs org
- CLAUDE.md at repository root describing app conventions

## Environment Variables (Vercel)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key for diagnostic pass |
| `GITHUB_TOKEN` | Fine-grained PAT scoped to this repo (contents:write, metadata:read) |
| `GITHUB_REPO` | `owner/repo` format (e.g. `Open-Scaffold-Labs/OpenRestaurant`) |
| `SELF_HEAL_CALLBACK_TOKEN` | Shared secret for webhook auth (generate with `openssl rand -hex 32`) |
| `SELF_HEAL_ENABLED` | Set to `true` to enable the self-heal dispatch button |

## GitHub Repository Secrets

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key for repair-pass agent |
| `SELF_HEAL_CALLBACK_TOKEN` | Must match the Vercel environment variable |

## Database Migration

Add the bug-report table to your application schema. Replace `PREFIX_` with your app's table prefix.

> **Note:** The schema below uses UUID types for Supabase (`auth.users` uses UUIDs). If your app also needs to run locally with INTEGER user IDs (e.g. during development), implement runtime type detection in your `ensureBugReportsTable()` function — query `information_schema.columns` to detect `users.id` type and create matching pk/fk columns. See OpenFirehouse commit `aaef555` for the reference implementation.

```sql
CREATE TABLE PREFIX_bug_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT now(),
  user_id UUID REFERENCES auth.users(id),
  description TEXT NOT NULL,
  page_route TEXT,
  context_bundle JSONB,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'diagnosed', 'resolved', 'failed')),
  diagnosis JSONB,
  diagnosis_tokens JSONB,
  diagnosis_duration_ms INTEGER,
  self_heal_status TEXT CHECK (self_heal_status IN ('queued', 'running', 'completed', 'failed')),
  self_heal_run_id TEXT,
  self_heal_branch TEXT,
  self_heal_pr_url TEXT,
  self_heal_pr_number INTEGER,
  resolution_notes TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_PREFIX_bug_reports_status ON PREFIX_bug_reports(status);
CREATE INDEX idx_PREFIX_bug_reports_created ON PREFIX_bug_reports(created_at DESC);
CREATE INDEX idx_PREFIX_bug_reports_user ON PREFIX_bug_reports(user_id);
CREATE INDEX idx_PREFIX_bug_reports_self_heal ON PREFIX_bug_reports(self_heal_status);
```

## File Checklist

Verify all canonical files are present:

- [ ] `/CLAUDE.md` — Trust anchor (should already exist)
- [ ] `/SELF-HEAL-SETUP.md` — This file
- [ ] `/.github/workflows/self-heal.yml` — Copy from Limitless Stack templates
- [ ] `/scripts/self-heal-agent.js` — Copy from Limitless Stack templates
- [ ] `/server/src/routes/debug-agent.js` — Implement per app data model
- [ ] `/client/src/components/BugReporter.jsx` — Implement per app UI framework
- [ ] `/client/src/pages/DebugReportsPage.jsx` — Implement per app UI framework

## Verification

1. Submit a test bug report through the in-app UI
2. Confirm the diagnostic pass completes (check bug report status in admin view)
3. Trigger self-heal on a controlled, known bug
4. Verify PR opens with correct labels and context
5. Review and merge the PR through normal process
