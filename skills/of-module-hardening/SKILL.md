---
name: of-module-hardening
description: The OpenFirehouse module-hardening recipe — the HARDEN-THE-TAIL §0 "Definition of Bulletproof" gate as a mechanical checklist, plus the routeKit/zod route skeleton, the adversarial-test skeleton, and the D6 migration recipe (claim-by-stub → prod-first → code). Invoke BEFORE starting work on any OpenFirehouse module (hardening a Tier-2 scaffold, building a phase module like scheduling/logistics/permits/analytics, or re-showing a hidden module), and AGAIN before declaring a module done. Triggers include "harden <module>", "Phase 1/2/3/4/5 work", "bring <module> to the gate", "module hardening", "harden the tail".
---

# of-module-hardening — the ONE standard, mechanized

Program trust anchor: `openfirehouse/docs/HARDEN-THE-TAIL-GAMEPLAN-2026-07-21.md` (+ ruling
table `docs/TAIL-TRIAGE-2026-07-21.md`). Read the gameplan's §0 + the module's phase section
before any work. This skill turns that standard into steps a session cannot skip. All work in
the `~/openfirehouse-neris` worktree, explicit-path staging, never `git commit -a`.

## 1 · The gate — a module is DONE only when EVERY box closes

Work through these in order. Each box has a verify that COULD FAIL (lesson #29 — a check that
cannot fail verifies nothing).

- [ ] **Spec first, market-bar-as-spec.** Written per-module spec citing the domain research
      (what capable competitors ship) + Matt's field reality. Names goals, NON-goals, and the
      legal/records classification of EVERY write. "MVP then iterate" is not a spec.
- [ ] **Field-reality check with Matt BEFORE building.** One sentence from a working officer
      falsified the prevention wedge. Ask how HIS department actually runs this domain.
- [ ] **Schema in D6 order** (§3 below). RLS `dept_isolation` on every new tenant table;
      tenant key is `department_id` (never bake in `station_id` — the active_boards trap).
      Dale-gated where security/legal/DEFINER/FK-to-legal-records.
- [ ] **routeKit + zod on every route** (§2 below). Zero bare tenant reads outside the kit.
- [ ] **Adversarial tests, not happy-path** (§4 below).
- [ ] **Offline honesty where field-relevant.** New ops = new intent vocabulary on the ONE
      existing batch (`fi-sync/batch` pattern: client-minted idempotency UUIDs, refused-vs-
      failed taxonomy, reachable-side retry). NEVER a second sync engine, NEVER a merge engine.
- [ ] **Audit rules where legal/money-adjacent.** Append-only audit rows via `utils/auditLog.js`
      (SAVEPOINT-wrapped; `record_id` is INTEGER — never a UUID). Soft-delete on anything
      subpoenable. AI never writes the legal record.
- [ ] **Client UX to design standard.** Empty states with personality; visibility-aware polling;
      string-coerce both sides of id comparisons; iPad-first where mobile; ErrorBoundary wrap.
- [ ] **Live prod verification.** Read the write BACK from prod (or query as postgres). A 2xx
      is not persistence (the 201-that-rolled-back mayday lesson).
- [ ] **Records current.** CHANGELOG (public) · wiki narrative + log (private) · CLAUDE.md
      feature state · NotebookLM 9c8f refresh with content-verify query.

## 2 · Route skeleton (routeKit + zod)

Source of truth: `server/src/utils/routeKit.js`. Pattern every new/hardened route follows:

```js
const express = require('express');
const { z } = require('zod');
const { scoped, httpError, validate } = require('../utils/routeKit');
const router = express.Router();

const createSchema = z.object({
  name: z.string().min(1).max(120),
  // …strict shapes; .strict() so unknown keys refuse
}).strict();

router.post('/', validate(createSchema), scoped(async (req, res, tenantId) => {
  // scoped() fails CLOSED (401) with no tenant on the token — never default a tenant
  // writes: parameterized SQL, tenant key from the kit, NEVER from the request body
  // intentional errors: throw httpError(409, 'Human message', 'MACHINE_CODE')
}));
module.exports = router;
```

Rules: results/status axes are CLOSED SETS owned by the server (constants file + CHECK
constraint — never regex-match a result); completion-class writes have EXACTLY ONE door;
finalized records answer 409 unconditionally; camelCase legacy columns are quoted exactly
(`"updatedAt"` — verify against information_schema, never assume snake_case).

## 3 · D6 migration recipe (schema change = ONE change with its code)

1. **Verify the head**: `ls openfirehouse/docs/migrations/ | tail -3`. Never trust memory or docs.
2. **Claim by stub**: commit an EMPTY `docs/migrations/0NNN-<slug>.sql` immediately (F4 — four
   number collisions to date).
3. **Write additive SQL** (F13: destructive needs Matt's explicit sign-off). New tenant tables:
   `department_id INTEGER NOT NULL` + index + RLS enable + `dept_isolation` policy.
4. **Apply to PROD by hand** (Supabase SQL/MCP or `server/scripts/migrate.js` with prod URL) —
   `initDb()` fast-paths on existing DBs and will NOT apply it.
5. **Ledger it**: row in `of_schema_migrations` (migrate.js does this on success).
6. **Verify live by query**: select the new columns/policies on prod. The file being in git is
   not the column being in Postgres.
7. **Mirror into `server/src/db.js`** for fresh installs (and the initDb schema check if needed).
8. **Only now** push the dependent code. If the migration is gated and can't apply, HOLD BOTH.

## 4 · Adversarial test skeleton (minimum set per module)

File: `server/src/tests/<module>.test.js`; DB-backed cases follow the `TENANCY_TEST_DB` opt-in
pattern (`tenancyIsolation.test.js` is the reference). Run: `cd server && TENANCY_TEST_DB='postgresql://matthewlavin@localhost:5432/freestation' npm test`.

- **Cross-tenant refusal**: dept B's token can never read/write dept A's rows (list + by-id + write).
- **Role-gate refusal**: each write route refuses below its floor (member vs officer vs chief).
- **Replay/idempotency** (where writes queue or mint): same idempotency key twice → one row,
  `duplicate` answered as success; a replayed completion never double-mints.
- **Finalization guard** (where records finalize): 409 unconditional; no field mutable after.
- **The domain's documented failure mode** from the market research (e.g. scheduling:
  double-award race, skip-order grievance trail; logistics: passed-check-with-open-defect).
- **Schema honesty**: the exact statement the code will run, against prod schema, in a
  transaction with ROLLBACK — a check that could fail.

## 5 · Close-out

Suite green (`npm test` full, no new skips) · client build green · prod smoke after deploy
(cache-busted `/health` + one real `/api/*` read) · read the write back · records refresh (§1
last box) · update the program checklist in `wiki/team-tasks.md` (NEWEST FIRST) · `audit-before-claim` pass on every "done" statement.
