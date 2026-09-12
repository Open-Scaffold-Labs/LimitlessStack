# audit-before-claim — the evidence

Every rule in `SKILL.md` was earned by a specific failure. Those failures live here so the
operative file stays scannable. Read this to know WHY a rule exists, before arguing one does not
apply, or when adding one. Split from the 423-line flat SKILL.md on 2026-09-12; the narrative is
verbatim, and the operative blocks are NOT duplicated — they live in `SKILL.md` only.

---

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


---

## Recommendations are claims too, when the question was already researched

The exemption for "discussions of trade-offs / options" is narrower than it looks, and this is the
seam a real failure came through.

**A recommendation that contradicts our own prior research is a factual error, not a preference.**
"No surveyed vendor does X" is a fact. Proposing X while that sentence sits in a research page we
already paid for is not a difference of judgment — it is being wrong about something already
written down.

> ⬆ **the 3-step research check** is the operative form and lives in `SKILL.md`. Not repeated here.
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


---

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

> ⬆ **“Search the SUBJECT”** is the operative form and lives in `SKILL.md`. Not repeated here.
- `wiki/log.md:157` — searched `fix/fi-department-scoping` (2 incidental hits) and never
  `station_id`. Called an INTENTIONAL design a cross-tenant bug. **Second time on that same line
  of code.** The session's own conclusion: *"The decisive query — `grep 'P7|station_id-as-tenant|
  mirror station'` — took nine seconds."*
- `wiki/log.md:8306` — searched the gameplan, never `companion` / form factor. **Third
  occurrence**, and Matt had used nearly the same words twice: *"GROUND YOURSELF IN THE HISTORY."*
- `wiki/log.md:8333` — titled *"The Stack held the facts and still could not deliver them."*

> ⬆ **recall.sh exit codes 0/1/2** is the operative form and lives in `SKILL.md`. Not repeated here.
**Why this belongs in THIS skill and not in CLAUDE.md.** The corpus carries roughly 132 documented
behavioural rules against roughly 35 mechanical checks, and every relapse traced in the 2026-08-24
audit happened against a rule that existed **only as prose**. This skill is the component with the
best evidenced catch record. Putting the discipline inside a mechanism that demonstrably fires
beats adding rule #133 beside one.

> ⬆ **the honest limitation** is the operative form and lives in `SKILL.md`. Not repeated here.
### A CITATION is a claim too — resolve the path before you dispute it

Same failure, smallest costume. On 2026-08-24 I disputed a **correct** citation of
`client/src/design/tokens.css` by resolving it from memory to `openfirehouse-neris` — a tree that
does not contain that file at all — and nearly filed a false finding against a reader whose
evidence was exact (`openscaffold-wiki/wiki/log.md:11346`). That night's fix added the routing
line *"cite a repo with every path"* and recorded the residue plainly: *"the second trap —
resolving a relative path to the wrong repo — has no mechanical guard"*
(`openscaffold-wiki/wiki/log.md:11381`).

> ⬆ **whichtree.sh command + exit codes** is the operative form and lives in `SKILL.md`. Not repeated here.
Two facts that make guessing worse than useless here: `client/src/design/tokens.css` really is in
**two** trees (`limitless-stack-hub` and `the-match`), and one repo can have **four** working
trees — `OpenFirehouse-private` and `paperclip` each do. The folder name is not the repo.


---

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

> ⬆ **the 6-rung environment ladder** is the operative form and lives in `SKILL.md`. Not repeated here.
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

> ⬆ **how to report a genuine unavailability** is the operative form and lives in `SKILL.md`. Not repeated here.

---

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
