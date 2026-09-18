# START-HERE.md — How to drive Claude Code

Put all six markdown files in an empty folder, `git init`, add a `.env` with your
`DEEPGRAM_API_KEY` and `ANTHROPIC_API_KEY`, then open Claude Code there.

---

## Kick-off prompt

```
Read CLAUDE.md, PLAN.md, SCHEMA.md and SYNTHETIC-DATA.md in full before doing
anything.

Then confirm back to me, briefly:
- the phase protocol you'll follow
- the adapter boundary rule
- the gate precedence order
- the five verified facts about real Deepgram output

Do not write any code yet. After confirming, wait for me to name the first phase.
```

If the phase protocol comes back wrong or vague, correct it before a line of code
exists.

---

## Starting a phase

```
Start Phase P0 from PLAN.md. Build only this phase, then stop and report
as described in CLAUDE.md.
```

## After you've tested and it works

```
approved

Before we continue: explain Phase P0 in 5 bullets, and point me to the 1-2
functions I should understand for Q&A.
```

Then `git commit -m "P0 approved"` yourself.

## When a phase fails its test

```
Phase P2 test failed.
Expected: CHK_C_DEAD_AIR fails, naming the 47s gap
Actual: it passed
Output: <paste>

Fix this within Phase P2 only. Don't touch anything outside this phase.
```

**Still broken after two attempts:**

```
This isn't converging. Propose the simplest version of Phase P2 that still meets
its "done when" test, even if part of it is hardcoded. Explain the tradeoff.
```

## If Claude runs ahead

```
Stop. You've moved past the current phase. Revert anything outside Phase P2's
scope, and report only Phase P2.
```

## Checking scope creep

```
List every file you created or changed in this phase, and for each, which line
of PLAN.md it comes from. Flag anything not in the plan.
```

---

## Build day

**On arrival, once CIMET's data is in `data/cimet/`:**

```
CIMET's data has arrived and is in data/cimet/. We're switching from PLAN.md to
PLAN-BUILDDAY.md — read it now.

Everything in PLAN.md is already built and passing against synthetic data. Today
is integration, not a rebuild. The synthetic set stays as regression fixtures.

Start Phase D0. First action: run src/transcribe.py on their test recording so
Deepgram is working and cached while we do recon. Then recon only — no other
code. Answer the 13 questions in PLAN-BUILDDAY.md D0 and write them into
RECON.md. Tell me anything surprising about the format.
```

**Then, phase by phase:**

```
Start Phase D1 from PLAN-BUILDDAY.md. Remember: only the four adapter files may
change. If anything outside src/adapters/ needs to change, stop and tell me why
before changing it.
```

**Behind schedule:**

```
It's <time> and we're on Phase D3. Freeze is 10:15. Look at the remaining phases
and the cut order at the end of PLAN-BUILDDAY.md, tell me exactly what to cut,
and update the plan. Then continue.
```

**At freeze:**

```
FREEZE. No new features from here.
Start Phase D8. Work through the checklist in order and stop after each item so
I can verify it.
```

**Interview prep, once submitted:**

```
Act as a CIMET engineering manager interviewing me about this build. Ask the 8
hardest questions: architecture choices, what happens when the model is wrong,
cost per call, scaling to 30 retailers, false-positive risk on criticals, what
I'd do with another week, and what I built today versus beforehand. One question
at a time, and critique each answer.
```

---

## Things to hold the line on

- **Never let a phase run unapproved.** The point of this structure is that you
  understand every line by the time you present it.
- **Test it yourself.** Don't accept "it should work now" — run the command.
- **Commit after every approval.** That's your rollback.
- **Watch for scope creep in P5/D3 (Type B).** It's the phase most likely to
  swallow the day.
- **Respect the 10:15 freeze** even if D7 is half done. A working demo of less
  beats a broken demo of more.
