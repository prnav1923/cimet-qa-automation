# CLAUDE.md — Project rules

## What this project is

A QA automation engine for CIMET's CRM. Every phone sale is scored automatically
against its retailer's compliance checklist before it can be submitted. All
criticals pass → the sale auto-submits. Any critical fail → the sale is held, and
the reviewer sees the exact failing check, the transcript line, the audio
timestamp, and the check version that was live on the call date.

Built for a 12-hour solo hackathon at CIMET, Jaipur. Real CIMET data (recording,
lead dataset, check library, scoring sandbox) arrives on build day. Until then we
build against synthetic data that mimics the expected shapes.

## THE PHASE PROTOCOL — READ THIS FIRST

Development is split into phases. See `PLAN.md` (pre-build) and
`PLAN-BUILDDAY.md` (build day).

## Self-check before reporting

Before you report a phase complete, run its own "done when" commands yourself
and confirm they pass. If they fail, fix it and re-run — that loop is part of
the phase, not a separate step.

In your report, state:
- the exact commands you ran
- the actual output you got (paste it, don't summarise)
- anything that still fails, stated plainly

Never report a phase complete on code you have not executed. If you cannot run
something (missing key, missing audio file, needs my input), say so explicitly
rather than assuming it works.

I will then run the same commands myself. If my result differs from yours, tell
me what environment difference could explain it before changing any code.

**Rules, non-negotiable:**

1. Work on **one phase at a time**, and only the phase I explicitly name.
2. **Never start the next phase on your own.** Not if the current phase finishes
   early. Not if the next phase looks trivial.
3. When a phase is complete, **STOP** and report:
   - What you built (max 5 bullets)
   - Files created or changed
   - **Exact commands I run to test it**
   - Anything you assumed or improvised
4. Then wait. I test it myself and reply `approved` or with failure details.
5. Only after `approved`, and only when I name the next phase, do you continue.
6. If a phase is bigger than it looked, say so and propose a split. Never
   silently expand it.

**If I say "continue" without naming a phase, ask me which phase I mean.**

## Scope discipline

- Build **only** what the current phase says. No extra features, pages,
  libraries, or "while I was in there" refactors.
- If something seems missing from the plan, tell me. Don't just add it.
- Boring, readable code over clever code. This gets explained to judges and
  interviewers in Q&A.
- No premature abstraction. Two concrete implementations before one generic one.

## Stack — fixed, do not substitute

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Storage | SQLite (single file, `data/qa.db`) |
| Transcription | **Deepgram REST API** — `nova-3`, `diarize`, `utterances`, `punctuate`, `smart_format` |
| HTTP | `requests` (no Deepgram SDK — its major versions break imports) |
| Fuzzy matching | `rapidfuzz` |
| Audio slicing | `pydub` |
| UI | Streamlit |
| LLM (Type B extraction only) | Anthropic API, structured JSON output |
| Config | Plain dicts / JSON. No YAML, no pydantic-settings. |

Do not introduce: Docker, FastAPI, Postgres, LangChain, vector DBs, ORMs, async
frameworks, or a JS frontend. None are needed.

**Deepgram is called over plain REST**, never via `deepgram-sdk`:

```python
requests.post(
    "https://api.deepgram.com/v1/listen",
    params={"model": "nova-3", "smart_format": "true", "punctuate": "true",
            "diarize": "true", "utterances": "true"},
    headers={"Authorization": f"Token {key}", "Content-Type": mime},
    data=audio_bytes, timeout=300,
)
```

Response path: `results.channels[0].alternatives[0].words` for word timings;
`results.utterances[]` for speaker-separated turns. Use `utterances` as the turn
source — it is already segmented by speaker.

## Verified facts about real Deepgram output

These come from an actual test run. Build for them; do not assume a cleaner world.

1. **Every word carries `start`, `end`, `confidence`, `speaker`,
   `speaker_confidence`, `punctuated_word`.** Use `punctuated_word` for display,
   the lowercase `word` for matching.
2. **Spoken numbers fragment.** "thirty one point nine cents" came back as three
   tokens: `31` / `percent` / `9¢`. Type B comparators **must** reassemble
   adjacent numeric tokens and normalise units, and must return
   `LOW_CONFIDENCE` when reassembly is ambiguous. Never string-match a rate.
3. **Per-word confidence varies hugely** — most words above 0.95, a misheard one
   at 0.30. This is a real signal: a verbatim match containing a low-confidence
   word must be penalised, not passed.
4. **Timestamps are not strictly monotonic.** Observed: one word ending at 14.24
   while the next starts at 13.515. All gap, overlap, and dead-air logic must
   tolerate out-of-order and overlapping spans, and must never produce a negative
   duration.
5. **`speaker_confidence` is often low (0.3–0.5)** even when diarization is
   right. Treat speaker labels as a hint. Never make a critical check depend
   solely on who was labelled as speaking.

## Architecture rule — the adapter boundary

**Nothing outside `src/adapters/` may know about external formats.**

```
CIMET check library  ──▶ adapters/load_checks()     ──▶ Check objects
CIMET lead dataset   ──▶ adapters/load_leads()      ──▶ Lead objects
Deepgram / CIMET txt ──▶ adapters/load_transcript() ──▶ Transcript object
                                                          │
                     engine / gate / ui / dashboard ◀─────┘
                                                          │
                           adapters/map_to_payload() ──▶ CIMET sandbox
```

On build day only these four functions change. If real CIMET data forces a change
anywhere else, that is a design bug — flag it immediately rather than patching
around it.

- `Check` and `Lead` carry `raw: dict` holding the untouched source record, so
  unknown columns survive.
- Every optional field has a default. A missing column must never crash a load.
- When a loader supplies a default the source didn't have, record it in
  `provenance`, so the demo can honestly state what we drafted versus what CIMET
  supplied.

## Correctness rules from the brief

These are scored. Do not deviate.

1. **Three outcomes per check**, never two: `PASS`, `FAIL`, `LOW_CONFIDENCE`.
2. **Gate precedence**, in this exact order:
   ```
   any critical FAIL        → HELD          (TL queue)
   elif any LOW_CONFIDENCE  → QA_REVIEW     (QA queue)
   elif sampled             → AUTO_SUBMIT + QA sample copy
   else                     → AUTO_SUBMIT
   ```
   A sampled sale **still submits**. Sampling never holds a sale.
3. **The 5% sample is deterministic**, by hashing the lead_id — never `random`.
   Same lead, same outcome, every run.
4. **Checks resolve by call date**: `effective_from <= call_date < effective_to`.
   Never "today's version".
5. **Nothing uncertain auto-passes.** Low confidence always routes to a human.
6. **Human overrides are logged**: actor, old status, new status, reason, time.
7. **No auto-correction.** Report what failed and where. Never rewrite the sale,
   override the agent, or contact the customer.
8. **Card data redacted in the transcript view**, violation still flags. The
   number is never displayed.
9. **Consent is a check, not an assumption.** Verify the disclaimer was read;
   never infer it from a recording existing.
10. **Test data only.** No real PII, ever.

## Repo layout

```
cimet-qa/
├── CLAUDE.md  PLAN.md  PLAN-BUILDDAY.md  SCHEMA.md  SYNTHETIC-DATA.md
├── README.md                # written in the final phase
├── requirements.txt
├── .env                     # DEEPGRAM_API_KEY, ANTHROPIC_API_KEY (gitignored)
├── data/
│   ├── synthetic/           # generated dummy data
│   ├── cimet/               # real CIMET data, build day only
│   ├── cache/transcripts/   # Deepgram responses by file hash
│   └── qa.db
└── src/
    ├── models.py            # dataclasses
    ├── db.py                # SQLite schema + access
    ├── adapters/            # THE ONLY FORMAT-AWARE CODE
    │   ├── load_checks.py  load_leads.py
    │   ├── load_transcript.py  map_to_payload.py
    ├── checks/
    │   ├── type_a_verbatim.py  type_b_factual.py
    │   ├── type_c_behaviour.py  comparators.py
    ├── engine.py  gate.py  accuracy.py  transcribe.py
    └── ui/app.py
```

## Caching — mandatory

- **Every Deepgram response is cached** to `data/cache/transcripts/<sha256>.json`
  keyed by audio file hash. Never re-transcribe the same file.
- **Every LLM response is cached** in the `llm_cache` table by input hash.
- Both caches mean the demo runs with the network off. Verify that before the
  demo, not during it.

## Git discipline

I commit after each approved phase. Don't commit for me. Never `git reset`,
`rebase`, or force-push — tell me and I'll do it.

## When you're unsure

Ask me. One question answered in ten seconds beats an hour of rework —
especially about the shape of CIMET's real data. Stub it rather than guess it.
