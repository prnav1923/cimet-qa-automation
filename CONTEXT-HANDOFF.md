# Context handoff — CIMET hackathon, QA Automation build

Paste this as the first message in the new chat.

---

I'm at the CIMET AI hiring hackathon in Jaipur (12-hour solo on-site build,
`/areas/` — repo path `/Users/pranav/Code/CIMET`). I need you to pick up as my
advisor mid-build. Here's the full context.

## The brief I chose

CIMET's "QA Automation" brief: every phone sale in their CRM must be scored
automatically against that retailer's compliance checklist before it can submit.
All criticals pass → auto-submit untouched. Any critical fail → held, with the
exact failing check, transcript line and audio timestamp next to it.

Today an auditor listens to a 30-minute call end to end, fills an Excel form,
and the sale waits. Thousands of sales a month across ~30 retailers.

Three check types: **A verbatim** (transcript vs approved script),
**B factual** (transcript vs CRM fields vs rate card), **C behaviour** (dead
air, interruptions, talk ratio — never blocks).

Judging: scoring accuracy 30%, coverage 25%, traceability 20%, gate &
escalation 15%, guardrails 10%. Demo is a live run; slides only support it.

I chose this over the other brief (a real-time AI voice agent for dropped-lead
recovery) because voice is too fragile to demo live solo.

## What CIMET actually supplied on the day

Only a **redacted PDF transcript** of one real call. No audio, no timestamps,
no check library, no lead data, no scoring sandbox. The call is a **broadband**
sale (not energy), and speaker separation is unreliable — the customer's
replies appear run-together inside the agent's rows.

## Key design decisions

- **Estimated vs measured timestamps are structurally separate fields**
  (`estimated_ts` vs `start_ts`), never both populated. UI renders
  "≈MM:SS (estimated — no audio supplied)" vs "🎧 MM:SS". I refused to
  synthesise audio or fake timings.
- **Fourth status `NOT_APPLICABLE`** for checks that can't be evaluated with
  the data supplied. Critical → routes to a human; non-critical → excluded from
  scoring so a clean lead can still auto-submit.
- **Gate precedence:** critical FAIL → HELD (TL queue); else any
  LOW_CONFIDENCE → QA_REVIEW; else AUTO_SUBMIT. Plus a deterministic 5% sample
  (md5 of lead_id) of clean calls that still auto-submit but also go to a human.
- **Adapter boundary:** only `src/adapters/` knows external formats.
- **Deterministic first, LLM only where judgement is needed.** 8 of 14 checks
  make no model call at all.
- Dead air returns NOT_APPLICABLE on their transcript because it needs real
  audio timing. I won't invent a number.

## Current state — the build works

- `CIMET_REAL_CALL` → **HELD**, driven by `CHK_B_TOTAL_COST FAIL, 42.90 vs 317`
  (agent says total minimum cost is $42.90 with no extra cost; the form the
  customer is looking at shows $317). Real extraction, real evidence, line
  numbers 30 and 78.
- Also passing on the real call: recording disclaimer (99% match against their
  mangled transcription), identity verification, promo/revert price consistency,
  and a **mute-before-payment guardrail** (agent muted the recording before
  collecting card details — the brief's "no card data by voice" boundary).
- 14 synthetic energy leads, **14/14 matching the expected-outcomes oracle**,
  covering all four gate branches including a sampled clean lead.
- Streamlit UI: lead list, scorecard, evidence panel with transcript line
  highlighted in context, override logging with mandatory actor + reason, card
  number masking, three queue tabs.
- Stack: Python, SQLite, rapidfuzz, Streamlit, Groq (`openai/gpt-oss-120b`) for
  Type B extraction only, Deepgram REST written but unused (no audio supplied).

## What's left

Four UI fixes in flight (queue-tab clicks don't switch the detail view;
truncated "Evidence" buttons; the header reason line is a semicolon dump of
check ids; default the app to open on the CIMET lead). Then README, slides,
rehearsal, submit.

I'm nearly out of Claude Code budget, so I'm writing the README and slides
myself.

## What I need from you

Advice only, no code. Help me with the README, the 5-minute demo script, Q&A
prep, and keeping me honest about scope. I have a documented tendency to
over-plan and under-ship, so bias me toward finishing and rehearsing rather than
adding anything.

Tell me how much time I have left and I'll tell you where I am.
