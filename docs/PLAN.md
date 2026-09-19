# PLAN.md — Pre-build phases

**Active plan.** On build day this is superseded by `PLAN-BUILDDAY.md`.

Goal: arrive at the hackathon with a working engine driven by synthetic data, so
build day is *integration plus the CIMET-specific parts*, not a build from zero.

**Phase protocol applies — see `CLAUDE.md`. One phase at a time. Stop and report.
Wait for `approved`.**

Target 6–8 hours across two sessions. If running long, cut P7 first, then P6.
Never cut P3 (traceability) or P4 (gate).

| Phase | What | Est. |
|---|---|---|
| P0 | Scaffold, deps, schema | 30 min |
| P1 | Synthetic data generator | 75 min |
| P2 | Type A verbatim + Type C behaviour | 90 min |
| P3 | Review UI with click-to-audio | 90 min |
| P4 | Gate, queues, overrides | 60 min |
| P5 | Comparators + Type B scaffolding | 90 min |
| P6 | Deepgram transcription + cache | 45 min |
| P7 | Accuracy harness + payload mapper | 45 min |

---

## P0 — Scaffold

**Build**
- Repo layout per `CLAUDE.md`
- `requirements.txt`: `requests`, `rapidfuzz`, `pydub`, `streamlit`,
  `anthropic`, `python-dateutil`, `python-dotenv`, `pytest`
  *(no `deepgram-sdk` — we call the REST API directly)*
- `.env.example` with `DEEPGRAM_API_KEY=` and `ANTHROPIC_API_KEY=`;
  `.gitignore` covering `.env`, `data/qa.db`, `data/cache/`
- `src/models.py` — every dataclass in `SCHEMA.md`, including the timing-safe
  properties (`Word.duration` never negative, `Transcript.sorted_turns()`)
- `src/db.py` — full SQLite DDL, `init_db()`, insert/select helpers
- `src/adapters/` — all four functions as stubs raising `NotImplementedError`
  with a docstring naming what they'll parse

**Done when**
```bash
pip install -r requirements.txt
python -c "from src.db import init_db; init_db()"
sqlite3 data/qa.db ".tables"
python -c "import src.models"
```
prints all six tables and imports cleanly.

**Do not** implement adapter logic in this phase.

---

## P1 — Synthetic data

**Build**
- `scripts/generate_synthetic.py` producing everything in `SYNTHETIC-DATA.md`:
  14 lead scenarios (including the two Deepgram-realism cases), 15 check rows,
  the DMO version change, rate card, auditor labels, `expected_outcomes.json`,
  silent MP3 placeholders
- `load_checks.py`, `load_leads.py`, `load_transcript.py` implemented **against
  the synthetic format**
- Transcripts must include the verified Deepgram flaws: varying per-word
  confidence with dips below 0.55, low `speaker_confidence`, at least one
  out-of-order timestamp pair, and fragmented number tokens

**Done when**
```bash
python scripts/generate_synthetic.py
python -c "
from src.adapters.load_leads import load_leads
from src.adapters.load_checks import load_checks
ls, cs = load_leads('data/synthetic/leads.json'), load_checks('data/synthetic/checks_retailer1.json')
print(len(ls), len(cs))
t = ls[0].transcript
print(t.turns[0].text, t.turns[0].start, t.turns[0].min_word_confidence)
print('overlaps ok:', all(w.duration >= 0 for w in t.words))
"
```
prints 14 and 15, a first turn with a real timestamp, and no negative durations.
Re-running the generator produces byte-identical files.

---

## P2 — Type A and Type C

**Build**
- `src/checks/type_a_verbatim.py`
  - sliding window over transcript words, `rapidfuzz.partial_ratio`
  - returns best similarity, matched span text, `start_ts`, `end_ts`
  - three outcomes via `pass_at` / `fail_at`
  - **a PASS whose matched span contains a word below
    `check.min_word_confidence` is downgraded to `LOW_CONFIDENCE`**, and the
    span's minimum ASR confidence is recorded on the result
- `src/checks/type_c_behaviour.py`
  - dead air: gaps over `max_dead_air_s`, computed as
    `max(0.0, next.start - cur.end)` on `sorted_turns()`; returns the longest gap
    and its timestamp
  - interruptions: count of overlapping turn spans (negative gaps)
  - talk ratio: agent speech seconds / total speech seconds
- `src/engine.py` — `score_lead(lead)`: resolve checks by call date, run each,
  persist `CheckResult` rows
- dispatch by type; Type B returns a `LOW_CONFIDENCE` placeholder for now

**Done when**
```bash
python -m src.engine --lead LEAD_3613790
```
and:
- `CHK_A_DISCLAIMER` → PASS with a timestamp around 12.4
- `CHK_C_DEAD_AIR` → FAIL naming the 47s gap and its timestamp
- the mumbled-DMO lead → `LOW_CONFIDENCE`, not PASS and not FAIL
- the low-ASR-confidence lead → `LOW_CONFIDENCE` despite a good fuzzy score
- the out-of-order-timestamp lead produces **no** phantom dead air
- the old-date lead resolves DMO **version 1**, and the row says
  `check_version=1`

That last one is the traceability proof — verify it explicitly.

---

## P3 — Review UI

**The most important pre-build phase.** 20% of the rubric, and the thing most
likely to eat an hour on the day.

**Build** — `src/ui/app.py`, Streamlit
- Left: lead list with gate status badge, retailer, agent, call date
- Main: scorecard, one row per check — status pill, description, critical marker,
  confidence, ASR confidence, expected vs actual for Type B
- **Click a failed check →** audio player seeks to `start_ts - 3s`, transcript
  line shown highlighted in context
- Transcript panel with the matched span highlighted
- Header: gate status, both scores, check-library version used, call date

**Audio seeking:** slice with `pydub` to a temp file and pass that to `st.audio`
(most reliable), rather than relying on a player start offset.

**Done when** the app runs, you open the worked-example lead, click the rate
failure, and hear the right part of the recording with the transcript line
highlighted — in under three clicks from launch.

---

## P4 — Gate, queues, overrides

**Build**
- `src/gate.py` — exact precedence from `CLAUDE.md`; deterministic
  `is_sampled()` by md5; both scores computed
- Persist `Decision` rows
- UI: three tabs — **TL queue** (held), **QA queue** (low confidence),
  **QA sample** (clean-but-sampled, clearly marked as already submitted)
- Override control per check: new status + actor + mandatory reason, writes an
  `Override` row and shows history inline
- Guardrail: card-number regex over the transcript; number masked in every view,
  violation flagged on the lead

**Done when**
```bash
python -m src.gate --all
```
- all 14 leads match `expected_outcomes.json`
- the sampled lead shows `AUTO_SUBMIT` **and** `sampled=true`
- an override writes a row with actor and reason, original status still visible
- the card-number lead shows the number masked but the violation flagged

---

## P5 — Comparators and Type B

**Build**
- `src/checks/comparators.py` — pure functions, no LLM:
  - `email` — exact after lowercase/trim
  - `rate` — **must reassemble fragmented number tokens.** Handles
    `"31.9"`, `"31.9c"`, `"thirty one point nine"`, and the real observed
    `["31", "percent", "9¢"]`. Returns `(value, confidence)`; ambiguous
    reassembly returns low confidence, never a guess.
  - `currency`, `date` (multiple formats), `phone`
  - `address` — normalise St/Street, Rd/Road, case, punctuation
  - `text`
- `src/checks/type_b_factual.py`
  - extraction prompt → strict JSON:
    `{field, spoken_value, transcript_line, start_ts, confidence}`
  - **resolver kept thin and isolated** — one function mapping
    `crm_field` / `plan_field` to a reference value. This is the piece most
    likely to change on build day.
  - LLM responses cached in `llm_cache` by input hash
  - low extraction or reassembly confidence → `LOW_CONFIDENCE`, never a silent
    pass on a critical

**Done when**
```bash
pytest tests/test_comparators.py -v
```
passes, including:
- `"12 Rundle St, Adelaide SA 5000"` vs `"12 Rundle Street, Adelaide SA 5000"` → match
- `j.smith@gmial.com` vs `j.smith@gmail.com` → no match
- `["31", "percent", "9¢"]` → reassembles to 31.9
- a garbled token sequence → low confidence, not a guess

and the worked-example lead FAILs both `CHK_B_PEAK_RATE` (expected 31.9, actual
28.6) and `CHK_B_EMAIL`, each with a timestamp; a second run makes zero API calls.

---

## P6 — Deepgram transcription

**Build** — `src/transcribe.py`
- `transcribe(audio_path) -> Transcript`
- Calls the Deepgram REST endpoint per `CLAUDE.md` (never the SDK)
- Content-Type inferred from extension: `.mp3` → `audio/mpeg`,
  `.wav` → `audio/wav`, `.m4a` → `audio/mp4`
- **Caches to `data/cache/transcripts/<sha256 of file>.json`.** Cache hit means
  zero API calls, and the function works with the network off.
- Maps `results.utterances[]` → `Turn`, with the word-field mapping in
  `SCHEMA.md`; falls back to `channels[0].alternatives[0].words` segmented on
  speaker change or a gap over 0.8s
- Speaker roles: whoever says the disclaimer is AGENT; otherwise `SPK_n`
- Plain-text fallback: align `LEAD_NOTS.txt` to Deepgram word timings by fuzzy
  token sequence; if alignment is poor, use Deepgram's own text and say so in
  `provenance`

**Done when**
```bash
python -m src.transcribe data/synthetic/audio/<any real mp3 you have>
```
returns a `Transcript` with word timings; running it a second time prints
`cache hit` and makes no network call; and with wi-fi off the cached call still
returns the transcript.

Use your real test recording here, not a silent placeholder.

---

## P7 — Accuracy and payload

**Build**
- `src/accuracy.py` — compare results to `auditor_labels`; report agreement
  overall and per check type, plus **false-passes on criticals** (must be zero)
- `src/adapters/map_to_payload.py` — internal results → `payload_shape.json`
- Minimal dashboard tab: first-pass yield, critical fail rate by check, repeat
  offenders (same critical failing 3+ times in a rolling 7 days)

**Done when**
```bash
python -m src.accuracy
python -m src.adapters.map_to_payload --lead LEAD_3613790
```
prints agreement %, per-type breakdown and a false-pass count (surfacing the one
deliberate auditor disagreement), and emits JSON matching `payload_shape.json`.

---

## Stop here

Do **not** pre-build: CIMET-format loaders, real payload mapping, retailer
onboarding, auth, deployment, or polish.

Before the event, verify: Deepgram key works and has credit for several 30-minute
calls; Anthropic key has credit; the app launches from a fresh terminal in under
a minute; the whole pipeline runs with wi-fi off using caches.
