# CIMET QA Automation: pre-submission compliance gate

Every phone sale is scored automatically against its retailer's compliance checklist before it can submit. If every critical check passes, the sale auto-submits untouched. If any critical check fails, the sale is held, and the reviewer sees the exact failing check, the transcript evidence, and where in the call it happened.

Today an auditor listens to a 30-minute call end to end, fills in an Excel form, and the sale waits. This replaces the listening with a gate and sends humans only the calls that need them.

## Result on CIMET's real call

CIMET supplied one redacted transcript of a real broadband sale. The engine **held** it on a critical pricing check:

- **Turn 32:** the agent tells the customer the *total minimum cost* is **$42.90**, with "no setup fee" and "no additional cost".
- **Turn 78:** the online order form the customer is reading shows a *total minimum cost* of **$317**.
- **Turn 82:** the agent tells the customer not to worry about it instead of reconciling the two figures.

The same phrase, "total minimum cost", is used for two different numbers, and the gap is never explained. `CHK_B_TOTAL_COST` fails → gate status **HELD**, routed to the team-lead queue with the evidence attached.

Also evaluated on the real call (all PASS): recording disclaimer read (99% match), identity verification, promo and revert prices ($42.90 / $72.90) stated consistently, and a guardrail confirming the recording was muted before payment details and resumed after.

## Results

```
$ python -m src.gate --all
lead_id          expected     actual       match  sampled
LEAD_3613790     HELD         HELD         True   False
LEAD_3613791     AUTO_SUBMIT  AUTO_SUBMIT  True   False
LEAD_3613800     AUTO_SUBMIT  AUTO_SUBMIT  True   True
LEAD_3613792     QA_REVIEW    QA_REVIEW    True   False
LEAD_3613793     HELD         HELD         True   False
LEAD_3613794     AUTO_SUBMIT  AUTO_SUBMIT  True   False
LEAD_3613795     HELD         HELD         True   False
LEAD_3613796     HELD         HELD         True   False
LEAD_3613797     AUTO_SUBMIT  AUTO_SUBMIT  True   False
LEAD_3613798     HELD         HELD         True   False
LEAD_3613799     AUTO_SUBMIT  AUTO_SUBMIT  True   False
LEAD_3613801     HELD         HELD         True   False
LEAD_3613802     AUTO_SUBMIT  AUTO_SUBMIT  True   False
LEAD_3613803     QA_REVIEW    QA_REVIEW    True   False
CIMET_REAL_CALL  -            HELD         None   False

14/14 leads with an oracle match
```

The 14 synthetic leads cover every gate branch: 6 held, 2 sent to QA review, 6 auto-submitted (one of which was also sampled for human review). **The expected outcomes are my own, written before the scoring code**, so this shows the logic works as designed, not accuracy against real auditor labels.

## How to run

```bash
python3.12 -m venv .qa && source .qa/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GROQ_API_KEY

python -m src.gate --all                    # score every lead, compare to expected outcomes
python -m src.engine --lead CIMET_REAL_CALL # per-check evidence for the real call
streamlit run src/ui/app.py                 # review UI
```

The synthetic leads need no network or API key. The two LLM-based checks on the real call are cached in `data/llm_cache.db`; with the cache present, the entire pipeline runs offline. That file is gitignored, so a fresh clone makes 6 Groq calls on first run. 429 responses are expected on Groq's token-per-minute limit, and the client retries using the wait time Groq reports.

## How it works

**Three check types.**
- **A, verbatim:** fuzzy match (rapidfuzz) of the transcript against approved script wording. A match containing a low-confidence ASR word is downgraded rather than passed.
- **B, factual:** values stated on the call compared to reference data, with normalisers for rates, currency, email, address, dates and phone numbers. Handles fragmented ASR numbers (`"31" / "percent" / "9¢"` → 31.9).
- **C, behaviour:** dead air, interruptions, talk ratio. Reported, never blocks a sale.

**Four statuses per check:** `PASS`, `FAIL`, `LOW_CONFIDENCE`, and `NOT_APPLICABLE` (can't be evaluated with the data supplied, e.g. dead air without audio). A critical `NOT_APPLICABLE` goes to a human; a non-critical one is excluded from scoring so it never blocks a clean sale on its own.

**Gate precedence, in order:**
1. Any critical `FAIL` or critical `NOT_APPLICABLE` → **HELD** (team-lead queue)
2. Else any `LOW_CONFIDENCE` → **QA_REVIEW** (QA queue)
3. Else → **AUTO_SUBMIT**, and a deterministic 5% sample (md5 of lead ID, never random) is also copied to a human. Sampling never holds a sale.

**Nothing uncertain auto-passes.** Low confidence always routes to a human.

**Traceability.** Every result records the check version that was live on the call date, the evidence line, and a timestamp. Measured timestamps (from audio) and estimated ones (derived from transcript position when no audio exists) are stored in separate fields and never both populated. The UI labels estimates "estimated — no audio supplied".

**Human overrides** require an actor and a reason, and are logged alongside the original status. Nothing is ever auto-corrected.

**Guardrails.** Card numbers are detected, masked in every view, and force a hold. The recording-mute check verifies payment details were taken off-record.

**Deterministic first, LLM only where judgement is needed.** The synthetic factual checks use regex extraction with no model call. The LLM (Groq, `openai/gpt-oss-120b`, strict JSON output, cached by prompt hash) is used only for the real call's unscripted pricing checks, where two independently extracted mentions of the same fact are compared for consistency.

**Adapter boundary.** Only `src/adapters/` knows external data formats. Onboarding CIMET's real check library or lead data means changing those loaders, not the engine.

## What CIMET supplied vs. what I drafted

| Item | Source |
|---|---|
| Call transcript (redacted PDF, one broadband sale) | CIMET |
| Audio, timestamps | Not supplied |
| Checklist for the real call (5 checks, all critical) | Drafted by me; no check library was supplied |
| Call date for the real call | Placeholder (`2026-01-01`); not in the transcript |
| 14 synthetic leads, 15-check energy checklist, expected outcomes | Generated by me |

Where a loader fills in a value the source didn't provide, it's recorded in `provenance`.

## Limitations and next steps

- **No audio.** Timestamps on the real call are estimates from transcript position; dead air can't be measured. Speaker separation in the supplied transcript is unreliable, so verbatim checks search the whole transcript rather than agent turns only.
- **One real call.** The synthetic 14/14 is against my own expected outcomes. The next step is scoring against real auditor labels to measure agreement and false passes on critical checks.
- **LLM line pointers drift.** On the real call, the model quoted turn 32 but reported turn 30, so the evidence panel highlights turn 30, with turn 32 visible directly below. The fix is to resolve the line from the model's quote by fuzzy matching, not to trust its line number.
- **Not built:** Deepgram transcription on real audio (client written, untested on CIMET data), accuracy harness, CIMET payload mapping, automated tests.
- **Behaviour checks on the no-audio path** (word-count talk ratio, run-together interruption detection) are implemented but not exercised by the real call's checklist.
- **UI:** queue tabs list leads but don't open them; use the sidebar.

## Stack

Python 3.12, SQLite, rapidfuzz, Streamlit, Groq REST API (via `requests`, no SDK). Deepgram REST client written for the audio path.

## Repo layout

```
src/adapters/   external formats (checks, leads, transcripts, payload) — the only format-aware code
src/checks/     type A verbatim, type B factual, type C behaviour, comparators
src/engine.py   resolves checks by call date, runs them, stores results
src/gate.py     gate precedence, sampling, overrides, card guardrail
src/ui/app.py   Streamlit review UI
data/cimet/     the supplied transcript and the drafted checklist
data/synthetic/ generated leads, checks, expected outcomes
```