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
  ALSO triggers before asserting that anything is broken, missing, never decided, or OPEN /
  UNRULED / the user's to decide; before declaring any tool, file, repo, skill, service or
  capability "unavailable", "unreachable", "not connected", "not installed", "missing" or "can't
  be done here"; and before citing or disputing a <repo>/<path>:line citation. Every one of those
  is a factual claim and needs the same evidence. Absorbed the former verify-before-claim skill
  2026-08-24.
---

# Audit Before Claim

**A statement is either verified or it is a hypothesis. Stating a hypothesis as a fact is the
prohibited move.** Everything below is one of two things: the test that decides, or the check that
settles one particular claim shape.

This file carries the RULES ONLY, so the triggers are the first thing read rather than the last.
The incidents that earned each rule are in **`references/incidents.md`** — read it when you want
to know why a rule exists, when you are about to argue one does not apply, or when you are adding
one. Bad-vs-good pairs per claim type are in **`references/examples.md`**.
⚠ **If your environment served this skill as a SINGLE FILE, those two files are not beside
you** — the Cowork account store takes only `SKILL.md`. Read them on the Mac through Desktop
Commander at `~/LimitlessStack/skills/audit-before-claim/references/`. A pointer you cannot
resolve is worse than no pointer, so resolve it there rather than reasoning without it.

## 🛑 STOP — five claim shapes, five checks

About to type something in the left column? Run the right column FIRST and put its result in your
reasoning. **At the moment you write the sentence — not at wrap-up.**

| About to claim… | Run this first |
|---|---|
| done · shipped · fixed · works · passes · a count · a percentage · "X is correct" | **The 95% Rule** below, plus the verification protocol for that claim type |
| broken · missing · not built · should be changed · "never decided" | `tools/recall.sh <subject noun>` — search the SUBJECT, never the artifact |
| a decision is **OPEN · UNRULED · SUSPENDED · the user's to make** | the gameplan's **§8 · DECISIONS FOR MATT** table, then `tools/recall.sh <subject noun>` |
| unavailable · unreachable · not connected · not installed · "can't be done here" | **the environment ladder** below — one "no" is one environment's answer, not the answer |
| any `<repo>/<path>:line` citation, before citing OR disputing it | `tools/whichtree.sh <bare/path>[:line]` |

**And with no phrase trigger at all — any substantive claim about OpenScaffold itself:**
architecture, a specific app (OpenFirehouse, FireHazmat, the Hub, OpenChiropractor, OpenSalon), the
Limitless Stack, Paperclip, Matt or Dale, CLAUDE.md protocol, table-prefix / seed-module / package
conventions, or **why we chose X over Y**. If the question *sounds* like you should already know
it, that is the trigger, not the exemption.

⚠ **Why the table is at the top.** In the 423-line flat version these triggers sat at lines 222+,
two-thirds down, behind narrative — and a session with this skill loaded broke three of them in one
afternoon. Length was not the defect; burial was. Do not push them back down.

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

Bad-vs-good pairs and the one-line evidence forms: **`references/examples.md`**.

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


## The four checks, in detail

### `recall.sh` — search the SUBJECT, and the exit code is load-bearing

**Search the SUBJECT, never the artifact.** A branch name, gameplan name, or filename is what the
work was *called*; the ruling that governs it is filed under what it was *about*. This is the
whole failure mode, and it has three recorded instances, two of them repeats of each other:



**Reading the result — the exit code is load-bearing:**

- **0** — hits found. Now do the work the tool cannot: decide whether these entries are **about**
  your subject or merely **mention** it. An artifact name matches incidentally everywhere. If no
  entry is a *ruling about the thing itself*, you searched the wrong noun — search again.
- **1** — the search ran and found nothing. This usually means **the wrong noun, not absent
  history.** It is not a licence to conclude "this was never decided."
- **2** — the search did not run (empty corpus / bad invocation). Nothing was checked. An empty
  result is meaningless unless the search actually happened.



**Honest limitation, stated so nobody over-trusts it.** `recall.sh` surfaces; it does not reason.
It cannot tell "about it" from "mentions it" — two heuristics for that were built and tested
against real data on 2026-08-24, and **both passed the known-bad control**, so neither shipped.
The discrimination is yours. The tool's only job is to make sure you cannot skip it.



### `whichtree.sh` — resolve a citation before you cite or dispute it

It has one now. A bare path is ambiguous **only because nothing resolves it**, and resolving it is
one command:

```
tools/whichtree.sh <bare/path>[:line]      # a full <repo>/<path> citation also works
```

It scans every working tree under `$HOME` — by remote, not by folder name — and says which ones
hold the path, ranked by HEAD commit date. **The exit code is the answer:**

- **0** — exactly one tree. Unambiguous; cite it.
- **3** — no tree holds it. The path does not exist as written.
- **4** — several trees hold it. **AMBIGUOUS** — resolve before citing. `NEWEST HEAD` marks the
  most recently committed tree; that is not evidence of which one the author meant.
- **5** — cited as `<repo>/<path>` where that repo does **not** hold it, but another does.
  **MISATTRIBUTED** — the exact shape of the error above.
- **2** — the scan did not run (zero trees enumerated). Nothing was checked; an empty answer is
  meaningless unless the search happened.



### The environment ladder — work it before reporting failure

**Work the environments before reporting failure.** One "no" is one environment's answer, not the
answer:

1. **Sandbox** — Bash/Python/Node, file tools. No Keychain, no GUI, no Mac filesystem except the mount.
2. **Workspace mount** — `/sessions/*/mnt/<folder>/`; readable from BOTH sandbox and Mac. The bridge.
3. **Desktop Commander** — runs on the Mac. Keychain, brew, `gh`, `git`, `python3.11`, `notebooklm`.
   Most sandbox failures are credential or path failures and clear here.
4. **Chrome MCP** — DOM, navigation, forms. Not connected ≠ unavailable; DC's `open` is a fallback.
5. **Computer Use** — native apps, after `request_access`.
6. **Ask the user** — last, and only with receipts for 1–5.



**How to report a genuine unavailability** — never the bare claim:

> "Tried X in the sandbox → `<error>`. Via Desktop Commander → `<result>`. Chrome MCP can't help
> because `<reason>`. Next step I'd suggest: `<concrete>`."

**The standard.** If the user can disprove your "unavailable" in thirty seconds by naming a path
you didn't try, you didn't work the list. And note the asymmetry with a plain wrong answer: a
false "it's broken" sends the user to fix something that isn't broken.



### The research check — a recommendation is a claim too

**A recommendation that contradicts our own prior research is a factual error, not a
preference.** "No surveyed vendor does X" is a fact.

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



## Skill self-test

Before closing a session, the user can ask: "What in your last summary was unverified?" Claude
should be able to answer that question precisely — listing any claims that were stated as fact
but weren't backed by fresh verification. If the answer is "nothing, every claim was verified" —
that is the win condition for this skill.

If Claude cannot answer that question, this skill is not being followed.


---

*Self-improvement protocol, the incidents behind every rule above, and the worked
examples live in `references/`. This file is the operative layer.*
