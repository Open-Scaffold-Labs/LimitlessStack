---
name: audit-before-claim
description: >
  Enforces a verify-then-state discipline. Every factual claim — about code correctness, task
  completion, test results, data accuracy, counts, percentages, fix verifications — must be backed
  by evidence Claude can cite from THIS session. If verifiable confidence is below 95%, the claim
  must be hedged or dropped, never asserted as fact. Triggers whenever Claude is about to: declare
  a task done, report a count or percentage, claim something "works" or is "fixed", summarize
  results, answer "did you finish X?". Use proactively before wrapping any non-trivial work and
  before any response that contains assertions of completeness, correctness, or success.
  ALSO triggers before declaring any tool, file, repo, skill, service or capability
  "unavailable", "unreachable", "not connected", "not installed", "missing", or "can't be done
  here" — an availability claim is a factual claim and needs the same evidence. Absorbed the
  former verify-before-claim skill 2026-08-24; see "It can't be done here" below.
---

# Audit Before Claim

## Why this skill exists

Under time pressure or context pressure, the cheapest path is to tell the user what they want to
hear: "done!", "all 448 enriched!", "tests pass!", "I fixed it!". That cheap path is the most
expensive thing Claude can do, because once a user catches Claude rounding up — even once — they
have to audit every future claim themselves. The productivity gain inverts.

The user does not want comfortable lies. The user wants truth, including bad news. A 60% truthful
report beats a 100% optimistic one every time.

Real examples of this failure pattern from prior sessions:

- Shipped 300 of 448 TIH materials enriched, then phrased the wrap-up to imply tier 1 was done.
  The user had to push back to surface that 148 remained.
- Almost shipped Phosgene IDLH = 0.41 ppm pulled from PubChem — actual NIOSH value is 2 ppm. The
  0.41 came from the parent heading mixing RD50 values into the IDLH section. Caught only because
  a 10-chemical reference set was hard-validated. Without that, 448 chemicals would have shipped
  with wrong IDLH values.
- Claimed "all tests pass" after editing a parser without re-running tests. Two were broken.
- Claimed "DATA_VERSION bumped" but forgot to actually save the file. The bump was real in chat,
  not on disk.

Each of these was a moment where the cheap claim ("done", "correct", "passes") would have shipped
wrong info. The pattern: trusting memory over fresh verification, trusting one tool result over
cross-checked sources, eliding "the parts I didn't actually verify" for narrative flow.

This skill makes that pattern mechanically harder.

## The 95% Rule

A statement can be made AS FACT only if Claude can answer **yes to ALL of the following** right now:

1. Can I cite the specific file:line, command output, or tool result from THIS session that proves
   this — without trusting memory of what was done earlier?
2. Have I executed the verification step on the actual artifact (not just inspected the code that
   would do the verification)?
3. If a second authoritative source disagreed with my claim, would I have a reason to trust mine?
4. Have I actively considered ways this claim could be wrong, and ruled them out?

If ANY answer is "no", the claim is below 95% and MUST be either:
- **Verified now** (preferred), or
- **Hedged explicitly** (e.g. "I believe X but haven't confirmed"), or
- **Dropped** from the response.

There is no middle ground. Either it's verified or it's a hypothesis. Stating a hypothesis as a
fact is the prohibited move.

## The "Don't Tell Them What They Want to Hear" Rule

If a verified-true finding undercuts the user's preferred outcome — surface it anyway. Sugar-coating
bad news, eliding partial completions, or implying success where verification is pending — all
violations.

Specifically forbidden softenings:

- "validation ran with some findings" → say "validation failed; here are the failures"
- "tier 1 substantially complete" → say "300 of 448 done, 148 remaining"
- "tests mostly pass" → say "42 of 44 tests pass; the 2 failing are X and Y"
- "the fix looks good" (without running it) → say "wrote the fix; haven't run it yet"
- silently dropping bad numbers from a coverage report → include EVERY field, even the zero rows

The user has explicitly stated they prefer 100% truth over reassurance. Honor that even when —
especially when — the truth means more work.

## Verification protocol by claim type

| Claim type | Required verification |
|---|---|
| "I wrote / changed X" | Re-read the file via Read tool; cite changed lines. |
| "X works" | Actually execute X. Capture output. Show evidence. |
| "X is correct" | Cross-check with a second authoritative source. |
| "Tests pass" | Run the test command; cite exit code AND output. |
| "All N items are Y" | Run a count or listing command; cite the actual number. |
| "X is fixed" | Reproduce original bug → apply fix → verify bug no longer reproduces. |
| "Y equals N" | Compute N from data RIGHT NOW; don't quote from memory. |
| "Task is done" | Walk the original task spec; verify each criterion is met. |

Concrete examples:

- "Lines 237-242 in src/db/index.ts now have matCols array of 45 entries."
- "Ran `npm test`; output: 87 passed, 0 failed."
- "NIOSH PG = 10 ppm; PubChem also returns 10 ppm; both match."
- "`pytest scripts/enrich/lib/__tests__/` → 42/42 passed, exit code 0."
- "`jq '[.materials[] | select(.is_tih and .enriched_at)] | length' hazmat.json` returned 384."
- "Before fix: CAS 7782-50-5 → CID 313 (HCl, wrong). After fix: CID 24526 (Cl2, correct)."

## Pre-claim audit checklist

Before sending ANY response that summarizes work, asserts results, or reports status:

1. **Enumerate every factual claim** in the planned response.
2. **Rate each claim's verification status:**
   - Verified in this session (cite the verification)
   - Verified earlier but not re-checked recently
   - Believed but not verified
3. **For each unverified claim:**
   - Easily verifiable now → verify before sending
   - Verifiable but expensive → hedge explicitly in the response
   - Not verifiable → drop the claim
4. **Actively look for counter-evidence.** What could make this claim wrong? Check that
   possibility before claiming.
5. **Surface unwelcome truths.** If verification reveals a problem that undercuts the user's
   preferred outcome, lead with it. Don't bury it. Don't soften it.
6. **Check for implicit claims.** Saying nothing about a step you skipped IS a claim that
   the step is fine. Either confirm it explicitly or list it as unverified.

## Anti-patterns this skill prohibits

- **Optimistic completion.** "Done!" before the run actually finishes, or after a partial run
  that you're framing as complete.
- **Memory-quoted numbers.** "300 materials enriched" when you haven't counted in this turn.
- **Test-pass-by-inference.** "Should be fine" without running the tests.
- **Vibes-based fix verification.** "I think this fixes it" — either prove it fixes the original
  repro or don't claim a fix.
- **Confidence laundering through tool results.** A tool returned a value ≠ the value is correct.
  PubChem returned 0.41 ppm for Phosgene IDLH; the actual NIOSH value is 2 ppm. The 0.41 came
  from the wrong sub-heading. Trust the path of the data, not just its presence.
- **Burying bad news.** If 6 of 50 reference chemicals didn't match, that's "12% miss rate, here
  are the misses" — not "passed validation."
- **Conflating intent and outcome.** "I wrote code intended to fix X" is not the same as "X is
  fixed." Keep them distinct.

## Self-improvement protocol

When a wrong claim slips through and the user catches it:

1. **Acknowledge directly.** No defense. No rationalization. "I was wrong about X. Here's what
   actually happened."
2. **Identify the verification step that was missing.** Which check, run NOW, would have caught
   this before sending?
3. **Add that check to this skill's protocol explicitly.** Edit this SKILL.md. The skill should
   get sharper each time it catches a slip.
4. **Append the incident to the session log.** Future Claude sessions should see the pattern.

Loud failures here are the most valuable training signal this skill has access to. Treat them
that way.

## When NOT to apply this overhead

Skip the audit pass for:

- Pure conversational responses with no factual claims ("how are you?", "what is X?")
- Clarifying questions to the user (the question itself is not a claim)
- Discussions of trade-offs / options (so long as the trade-offs are accurately described)
  — **but see "Recommendations are claims too" below: this exemption does NOT cover a
  recommendation that contradicts research we already hold.**
- Plain explanations of how something works in concept, when no claim of "I did this" is involved

Apply the audit pass for:

- Any claim of completion: done / shipped / fixed / works / passes / merged / deployed
- Any reported number, percentage, count, measurement, coverage stat, or rate
- Any architecture description ("the function does X") about code in the current session
- Any test-result, build-result, deploy-result statement
- Any summary the user is going to use to anchor a decision


## Recommendations are claims too, when the question was already researched

The exemption for "discussions of trade-offs / options" is narrower than it looks, and this is the
seam a real failure came through.

**A recommendation that contradicts our own prior research is a factual error, not a preference.**
"No surveyed vendor does X" is a fact. Proposing X while that sentence sits in a research page we
already paid for is not a difference of judgment — it is being wrong about something already
written down.

**The check, before proposing any behaviour change:**

1. **Has this been researched?** Look in `wiki/synthesis/`, `docs/`, and any market or competitor
   pass covering the domain. Search by SUBJECT, not by document name.
2. **If a research page speaks to it, cite it** — in the recommendation itself, so the next reader
   can see the proposal was weighed against the evidence rather than reasoned from scratch.
3. **If the research disagrees with you, you are wrong until you can say specifically why** it is
   stale, was measuring something else, or no longer applies. "It seems better" does not outrank a
   documented pass. Neither does an internally consistent chain of reasoning.

**The tell:** any recommendation of the form "we should probably…" about behaviour in a domain
where a competitor or market pass exists. Also: proposing to change something that currently
matches a documented standard.

**The incident that produced this rule (2026-08-19).** A forward plan proposed making an
authorisation refusal retryable rather than terminal, and ranked it the second priority. The
reasoning was coherent and internally consistent. The 2026-08-03 market research — not re-read
while drafting — said plainly: *"the fail-informatively path (submission rejections surfacing on
the report, which OF already ships) is the market-standard fallback and is already ours."* The
recommendation was to abandon a standard we already met, in favour of something no surveyed vendor
does, and it would have replaced a visible failure with an invisible one. Matt caught it by asking
"why would we do this?" — the audit pass did not, because it was auditing claims and this was
shaped like an opinion.

**Why this belongs in THIS skill rather than a style guide:** the failure mode is identical to the
one the rest of the file guards. Memory-quoted numbers and research-you-did-not-re-read are the
same error — trusting what you believe over what is written down and checkable. The fix is the
same too: go read the artifact before asserting.

## "It's broken / missing / never decided" is a claim about the HISTORY

Same failure as the section above, different costume. A recommendation that contradicts research
we already hold is a factual error; so is **an assertion that something is broken, absent, or was
never decided, when the history says otherwise.** Both are trusting what you believe over what is
written down and checkable.

**The trigger — four claim shapes, plus the whole OpenScaffold surface:**

> Before asserting **broken · missing · not built · should be changed**, run
> `tools/recall.sh <subject noun>` and paste the result into your reasoning.

> **Also before any substantive claim about OpenScaffold itself** — architecture, a specific app
> (OpenFirehouse, FireHazmat, the Hub, OpenChiropractor, OpenSalon), the Limitless Stack, Paperclip,
> Matt or Dale, CLAUDE.md protocol, table-prefix / seed-module / package conventions, or **why we
> chose X over Y**. If the question *sounds* like you should already know it, that is the trigger,
> not the exemption.

⚠ **This second trigger arrived here on 2026-08-24 from the deleted `four-tool-lookup` skill, and
the way it nearly got lost is the lesson.** That skill was correct and had **2** lifetime
invocations; it was deleted on that number. But invocation count measures whether a skill FIRED,
not whether it was RIGHT — and the same day's audit had already measured that these skills never
self-fire (2 `Skill()` calls in a 6 MB transcript, both because Matt typed the name). Its scope was
then left resting on `CLAUDE.md` prose alone, in a corpus where prose caught **0 of 9** errors that
session. Deleting an unused-but-correct guard and relying on a written rule is a lateral move, not
a simplification. **Never retire a guard on usage data alone: diff its content against what
remains, and move anything unique onto a lever that actually gets pulled — this one, at 47 lifetime
invocations.** Matt caught this; the deletion had already been staged.

**Search the SUBJECT, never the artifact.** A branch name, gameplan name, or filename is what the
work was *called*; the ruling that governs it is filed under what it was *about*. This is the
whole failure mode, and it has three recorded instances, two of them repeats of each other:

- `wiki/log.md:157` — searched `fix/fi-department-scoping` (2 incidental hits) and never
  `station_id`. Called an INTENTIONAL design a cross-tenant bug. **Second time on that same line
  of code.** The session's own conclusion: *"The decisive query — `grep 'P7|station_id-as-tenant|
  mirror station'` — took nine seconds."*
- `wiki/log.md:8306` — searched the gameplan, never `companion` / form factor. **Third
  occurrence**, and Matt had used nearly the same words twice: *"GROUND YOURSELF IN THE HISTORY."*
- `wiki/log.md:8333` — titled *"The Stack held the facts and still could not deliver them."*

**Reading the result — the exit code is load-bearing:**

- **0** — hits found. Now do the work the tool cannot: decide whether these entries are **about**
  your subject or merely **mention** it. An artifact name matches incidentally everywhere. If no
  entry is a *ruling about the thing itself*, you searched the wrong noun — search again.
- **1** — the search ran and found nothing. This usually means **the wrong noun, not absent
  history.** It is not a licence to conclude "this was never decided."
- **2** — the search did not run (empty corpus / bad invocation). Nothing was checked. An empty
  result is meaningless unless the search actually happened.

**Why this belongs in THIS skill and not in CLAUDE.md.** The corpus carries roughly 132 documented
behavioural rules against roughly 35 mechanical checks, and every relapse traced in the 2026-08-24
audit happened against a rule that existed **only as prose**. This skill is the component with the
best evidenced catch record. Putting the discipline inside a mechanism that demonstrably fires
beats adding rule #133 beside one.

**Honest limitation, stated so nobody over-trusts it.** `recall.sh` surfaces; it does not reason.
It cannot tell "about it" from "mentions it" — two heuristics for that were built and tested
against real data on 2026-08-24, and **both passed the known-bad control**, so neither shipped.
The discrimination is yours. The tool's only job is to make sure you cannot skip it.

## "It can't be done here" is a claim about the ENVIRONMENT

Third costume, same failure: asserting from belief instead of from a check. **"X is unavailable"
is a factual claim about the environment and needs a command behind it like any other.** Absorbed
from the former `verify-before-claim` skill, 2026-08-24 — that skill was written for exactly this,
was mounted the whole session it was needed, and was invoked **zero** times in five months against
this skill's 47. The content was right; the lever was wrong. One lever that gets pulled beats two
that don't.

**The trigger — stop if you are about to type any of these:**

> "X isn't available" · "X is unreachable" · "I don't have access to X" · "X isn't connected" ·
> "I can't access X from here" · "X isn't installed" · "there's genuinely nothing to check here" ·
> "that tool isn't working"

**Work the environments before reporting failure.** One "no" is one environment's answer, not the
answer:

1. **Sandbox** — Bash/Python/Node, file tools. No Keychain, no GUI, no Mac filesystem except the mount.
2. **Workspace mount** — `/sessions/*/mnt/<folder>/`; readable from BOTH sandbox and Mac. The bridge.
3. **Desktop Commander** — runs on the Mac. Keychain, brew, `gh`, `git`, `python3.11`, `notebooklm`.
   Most sandbox failures are credential or path failures and clear here.
4. **Chrome MCP** — DOM, navigation, forms. Not connected ≠ unavailable; DC's `open` is a fallback.
5. **Computer Use** — native apps, after `request_access`.
6. **Ask the user** — last, and only with receipts for 1–5.

**Before concluding a path does not exist, `ls` the parent.** The recorded failures are all the
same shape — the data was present at a different address:

- 2026-08-24, twice in one hour: *"the skills scanner has genuinely nothing to scan here"* — then
  `ls "$(dirname "$VAULT")/.claude/skills"` returned **18 entries**. The script was reading
  `$HOME/.claude/skills`, which does not resolve in that environment. The second assertion was
  prefaced *"I want to be accurate rather than agreeable,"* which made an unchecked claim sound
  like rigour. **That is worse than being plainly wrong**, and it is why a non-agreeable posture
  is not a substitute for a check.
- Same day: the trust-anchor checker reported 8-of-8 SKIP and exit 0 in a sandbox — reported as
  environment-bound, actually a hardcoded-path bug. Both were fixed by making the tool *discover*
  its target rather than guess one address.

**How to report a genuine unavailability** — never the bare claim:

> "Tried X in the sandbox → `<error>`. Via Desktop Commander → `<result>`. Chrome MCP can't help
> because `<reason>`. Next step I'd suggest: `<concrete>`."

**The standard.** If the user can disprove your "unavailable" in thirty seconds by naming a path
you didn't try, you didn't work the list. And note the asymmetry with a plain wrong answer: a
false "it's broken" sends the user to fix something that isn't broken.

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

## Skill self-test

Before closing a session, the user can ask: "What in your last summary was unverified?" Claude
should be able to answer that question precisely — listing any claims that were stated as fact
but weren't backed by fresh verification. If the answer is "nothing, every claim was verified" —
that is the win condition for this skill.

If Claude cannot answer that question, this skill is not being followed.
