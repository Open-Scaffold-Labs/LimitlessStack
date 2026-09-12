# audit-before-claim — worked examples

Bad-vs-good pairs for each claim type, and the one-line evidence forms. Referenced from
SKILL.md's verification protocol. Extracted verbatim 2026-09-12.

---

Concrete examples:

- "Lines 237-242 in src/db/index.ts now have matCols array of 45 entries."
- "Ran `npm test`; output: 87 passed, 0 failed."
- "NIOSH PG = 10 ppm; PubChem also returns 10 ppm; both match."
- "`pytest scripts/enrich/lib/__tests__/` → 42/42 passed, exit code 0."
- "`jq '[.materials[] | select(.is_tih and .enriched_at)] | length' hazmat.json` returned 384."
- "Before fix: CAS 7782-50-5 → CID 313 (HCl, wrong). After fix: CID 24526 (Cl2, correct)."


---

## Worked examples

### Example 1 — claim of completion (the 300/448 incident)

BAD:
> "Wrapped up Tier 1 with 300 TIH materials enriched. Coverage gains across IDLH, vapor density,
> and the new identity fields are substantial. Pipeline shipped."

What's wrong: implies tier 1 is complete; "wrapped up" frames a stop as a finish.

GOOD:
> "Stopped Tier 1 at 300/448 TIH materials (verified just now: `jq '[.materials[] | select(.is_tih
> and .enriched_at)] | length' hazmat.json` returns 300). 148 TIH materials remain unprocessed —
> mostly mixtures/n.o.s. that didn't match PubChem by name. To finish: `python3 scripts/enrich/
> enrich.py --tier 1 --resume`."

### Example 2 — claim of correctness (the Phosgene IDLH near-miss)

BAD:
> "Phosgene IDLH = 0.41 ppm, sourced from PubChem."

What's wrong: trusts the value without cross-checking. NIOSH PG says 2 ppm; the 0.41 came from
the parent heading mixing RD50 into IDLH responses.

GOOD:
> "PubChem returned 0.41 ppm for Phosgene from the parent 'Immediately Dangerous to Life or Health'
> heading, but cross-checking the SUB-heading specifically labeled 'IDLH' returns 2 ppm (NIOSH-
> tagged). NIOSH Pocket Guide also lists 2 ppm. The 0.41 was probably an RD50 (50% respiratory
> rate decrease) value bleeding in from a sibling sub-section. Using 2 ppm; pinning the parser
> to the named sub-section to avoid the bleed."

### Example 3 — claim of "fix"

BAD:
> "Fixed the GHS pictogram bug."

What's wrong: doesn't say what was broken, doesn't show the fix took.

GOOD:
> "GHS pictogram parser was checking the `Extra` field for codes like 'GHS02', but PubChem puts
> the human-readable label there ('Flammable', 'Health Hazard'). The actual code is in the URL
> field ('.../GHS02.svg'). Rewrote the parser to extract from URL via regex `(GHS0[1-9])\\.`.
> Tested on Benzene CID 241: now returns ['GHS02', 'GHS07', 'GHS08']. Need to re-run enrichment
> on already-processed materials for them to get GHS data."

### Example 4 — claim of test pass

BAD:
> "Tests pass."

What's wrong: which tests? what command? what output?

GOOD:
> "Ran `python3 scripts/enrich/lib/__tests__/test_normalizers.py`. Result: 42/42 passed, 0 failed.
> Exit code 0. (TypeScript compilation also clean for src/db, src/types, src/screens/MaterialDetail
> — `npx tsc --noEmit | grep <those paths>` returns no errors; 11 pre-existing errors elsewhere
> are unrelated to this session's changes.)"

