# HANDOFF.md

Read this first, then `CLAUDE.md` (project rules, non-negotiable) before touching
code. `PLAN.md` / `PLAN-BUILDDAY.md` describe the *original* phase plan — see
"Why the phase plan diverged" below for why the actual build doesn't match it
past P2.

## What this project is

A QA automation engine for CIMET's CRM: every phone sale gets scored against
its retailer's compliance checklist (disclaimer read, ID verified, prices
quoted correctly, etc.) before it can submit. Any critical check that fails
holds the sale for a human reviewer instead of auto-submitting it; nothing
uncertain is ever auto-passed. Built for a 12-hour solo hackathon at CIMET —
synthetic data first, then a real CIMET transcript arrived mid-build.

## Current state — what works

Run `python -m src.gate --all` right now and you get **14/14 synthetic leads
matching their expected outcome**, plus one real lead (`CIMET_REAL_CALL`)
correctly `HELD`. Concretely, built and verified with real command output
(not mocked):

- **P0/P1/P2** (from `PLAN.md`, committed early): scaffold, synthetic data
  generator (`scripts/generate_synthetic.py`, 14 leads + fixtures, seeded/
  deterministic), Type A verbatim checks (`src/checks/type_a_verbatim.py`,
  rapidfuzz-based), Type C behaviour checks (`src/checks/type_c_behaviour.py`
  — dead air, talk ratio, interruptions), scoring engine (`src/engine.py`).
- **CIMET's real transcript path**: `data/cimet/call-transcript-redacted.json`
  (parsed once from the supplied PDF via `scripts/extract_cimet_transcript.py`,
  a one-off — don't re-run it as part of the live pipeline). It has no audio,
  no timings, unreliable speaker separation. `src/adapters/load_transcript.py`
  handles this as a second source format: estimated word timestamps at
  ~150wpm, `has_word_timings=False`, everything downstream keys off that flag
  rather than guessing. `CheckResult` carries `estimated_ts`/`estimated_end_ts`/
  `line_number` for this source, never `start_ts`/`end_ts` — the two are
  mutually exclusive by construction, never both populated.
- **Four-outcome status model**: `PASS` / `FAIL` / `LOW_CONFIDENCE` /
  `NOT_APPLICABLE` (added because the CIMET path genuinely can't evaluate
  some things — e.g. dead air needs measured audio it doesn't have).
  `NOT_APPLICABLE` on a **critical** check routes to a human exactly like
  `LOW_CONFIDENCE`; on non-critical it's excluded from scoring, never blocks
  `AUTO_SUBMIT` alone.
- **`src/gate.py`**: exact precedence from `CLAUDE.md` (critical FAIL/
  NOT_APPLICABLE → HELD, elif LOW_CONFIDENCE → QA_REVIEW, elif sampled →
  AUTO_SUBMIT+QA copy, else AUTO_SUBMIT), deterministic 5% sampling (md5 of
  lead_id, never `random`), human overrides logged with actor/reason
  (mandatory fields), card-number guardrail (regex-detects and masks, forces
  HELD, number never displayed).
- **`src/ui/app.py`**: Streamlit review UI — sidebar lead list, scorecard,
  click-a-check-to-see-evidence, 3 queue tabs (TL/QA/sample), override form,
  card masking. Two real bugs found and fixed during build: `sys.path` not
  including repo root under `streamlit run` (fixed with an explicit
  `sys.path.insert`), and a `sqlite3` cross-thread error from Streamlit's
  per-session threading model (fixed with `check_same_thread=False`).
  **Caveat**: verified via `streamlit.testing.v1.AppTest` and a real
  background `streamlit run` process (log-checked for errors), **not** by
  anyone actually clicking through it in a browser. Do that before calling
  the UI phase done.
- **Type B factual checks**, two extraction paths in
  `src/checks/type_b_factual.py`:
  - **Deterministic regex** (no LLM, no network, no quota) for the six
    synthetic ground-truth checks (`CHK_B_PEAK_RATE`, `_DAILY_SUPPLY`,
    `_EMAIL`, `_ADDRESS`, `_DOB`, `_NMI`). Works because the synthetic
    transcript generator's wording is fixed and known — the value is always
    the turn right after a known anchor sentence. Handles spelled-out numbers,
    fragmented ASR-style tokens (`"31"/"percent"/"9¢"` → 31.9, the real
    Deepgram quirk from `CLAUDE.md`), and correctly returns `LOW_CONFIDENCE`
    when a value is genuinely unparseable (`"thirty one ish cents or
    something"`). This is why the 14 synthetic leads pass with zero API calls.
  - **LLM extraction** for CIMET's real, unscripted checklist (the
    `"consistency"` comparator — no CRM/plan ground truth exists for CIMET,
    so two independently-extracted mentions of the same fact are compared to
    each other instead). Strict JSON contract:
    `{field, spoken_value, transcript_line, line_number, confidence}`,
    cached by SHA-256 of the prompt. **Provider history**: Anthropic (no key
    available) → Gemini (hit its free-tier wall, `20 requests/day`, genuinely
    exhausted — confirmed via raw API testing, not assumed) → **Groq**
    (current, working). Groq is called at `POST
    https://api.groq.com/openai/v1/chat/completions` with `requests` (no SDK,
    same reasoning as Deepgram in `CLAUDE.md`), model `openai/gpt-oss-120b`
    (`llama-3.3-70b-versatile` 404s on this account — confirmed via
    `GET /v1/models`, don't re-guess model names, just hit that endpoint),
    `response_format: {"type": "json_object"}`. Groq's 8000 TPM cap on this
    model is *smaller* than one prompt (~4.5k tokens, since the whole
    transcript is in context) — `_call_llm` has a bounded retry (max 6
    attempts) that parses Groq's exact `"try again in Xs"` / `"Xms"` wait out
    of the 429 body and sleeps that long. Both units matter — an earlier
    version only matched `ms` and silently failed on `s`-suffixed messages.
  - Both paths feed the same `_values_match` comparator (rate/currency,
    email, address, date, phone, text) — extraction method never changes the
    comparison logic.
  - `llm_cache` lives in its **own file**, `data/llm_cache.db`, attached into
    every connection via SQLite `ATTACH DATABASE` (see `src/db.py`), not as a
    table inside `data/qa.db`. This was deliberate: `qa.db` gets deleted
    constantly during dev (`rm -f data/qa.db` to force a clean re-run), which
    was repeatedly wiping the cached Gemini/Groq extractions and burning
    quota re-fetching them. **Never delete `data/llm_cache.db`** unless you
    intend to re-spend API quota — it's gitignored, so it doesn't travel with
    the repo, and a fresh clone starts with an empty cache.

## Where CIMET_REAL_CALL stands

`CIMET_REAL_CALL` (in `data/cimet/leads_cimet.json`, checklist in
`data/cimet/checks_cimet.json` — 5 checks, all critical, drafted by us since
CIMET didn't supply an approved script) currently scores:

| Check | Status | Detail |
|---|---|---|
| `CHK_A_DISCLAIMER` | PASS | 99% match against drafted expected wording |
| `CHK_A_IDENTITY` | PASS | 100% match |
| `CHK_B_TOTAL_COST` | **FAIL** | agent states **$42.90** (turn 30) as the total minimum cost, but a much larger figure, **$317**, appears later (turn 78, on the order form the customer is reading) — genuinely inconsistent, this is a real defect in the call |
| `CHK_B_PROMO_PRICE` | PASS | promo price ($42.90) and revert price ($72.90) each independently confirmed consistent across two mentions |
| `CHK_GUARDRAIL_MUTE` | PASS | recording muted before payment details, resumed after |

**Gate status: `HELD`**, reason `CHK_B_TOTAL_COST=FAIL` (critical FAIL always
forces HELD regardless of everything else). This is the intended, correct
outcome — `$42.90` vs `$317` is a real pricing-consistency problem in that
call, not a scoring bug.

Both Type B results are cached in `data/llm_cache.db` — re-running
`python -m src.engine --lead CIMET_REAL_CALL` costs zero API calls unless
that file is deleted.

`CIMET_REAL_CALL` has **no entry in `expected_outcomes.json`** (that file is
synthetic-only, hand-authored during P1 before the real transcript existed) —
`gate --all`'s report correctly shows it as `note: no expected outcome on
file` rather than forcing a match/mismatch verdict. That's expected, not a bug.

## Exact commands to run and verify

```bash
source .qa/bin/activate

# Full regression: 14 synthetic leads (deterministic, no network) + the one
# real CIMET lead (needs GROQ_API_KEY in .env unless llm_cache.db already
# has the two extractions cached, which it does right now).
python -m src.gate --all

# Expect: 14/14 leads with an oracle match, CIMET_REAL_CALL = HELD.

# Look at just the real call in detail (prints per-check evidence, timestamps):
python -m src.engine --lead CIMET_REAL_CALL

# Expect: CHK_B_TOTAL_COST FAIL, expected='42.90' actual='317'.

# UI (manual browser check still outstanding, see above):
streamlit run src/ui/app.py

# DB schema sanity check after any model/db.py change:
rm -f data/qa.db   # safe -- does NOT touch data/llm_cache.db
python -c "from src.db import init_db; init_db()"
sqlite3 data/qa.db ".schema check_results"
```

If `gate --all` shows `LOW_CONFIDENCE` on either CIMET Type B check instead
of the table above, `data/llm_cache.db` is either missing or the two prompts
changed (re-run costs 6 real Groq calls: 2 for `CHK_B_TOTAL_COST`, 4 for
`CHK_B_PROMO_PRICE`, since `_score_consistency` always extracts both sides of
every pair regardless of earlier failures). If you hit 429s, that's normal
Groq TPM behaviour on this model, not a bug — `_call_llm` already retries
correctly using the wait time Groq itself reports.

## Remaining tasks

1. **Manually click through the UI in a real browser** — only AppTest/log-based
   verification has been done. `streamlit run src/ui/app.py`, load a HELD lead
   (e.g. `CIMET_REAL_CALL` or `LEAD_3613790`), click a failed check, confirm
   the evidence panel and override form both work end-to-end.
2. **README.md** — not written yet; repo layout comment in `CLAUDE.md` says
   "written in the final phase."
3. **`requirements.txt` still lists `anthropic`**, unused since the provider
   moved to Gemini then Groq. Never removed because each swap was scoped to
   "don't expand scope" and removing a dependency wasn't asked for. Safe to
   drop.
4. **Type C behaviour checks (dead air / talk ratio / interruptions) are
   built for the CIMET no-audio path but never exercised** — `checks_cimet.json`
   only has 5 checks (2× Type A, 2× Type B, 1× Type C guardrail-mute) and
   none of them are `CHK_C_DEAD_AIR`/`CHK_C_TALK_RATIO`/`CHK_C_INTERRUPTIONS`.
   The run-together-acknowledgment interruption detector and word-count talk
   ratio in `src/checks/type_c_behaviour.py` were built per an earlier
   approved plan but have no real check row driving them against
   `CIMET_REAL_CALL` — only reachable today via the synthetic checklist,
   which has real audio timings and uses the other code path. If CIMET's
   real checklist grows to include talk-ratio/interruption rules, this is
   where they'd plug in, but nobody has looked at what a plausible threshold
   is for this call format.
5. **No automated tests** — `tests/` exists but is empty; `pytest` is a
   listed dependency with nothing to run yet.
6. **P6 (Deepgram transcription on real audio) and P7 (accuracy/payload)
   from `PLAN.md` were never built** — `transcribe.py` and `accuracy.py`
   don't exist. `src/adapters/map_to_payload.py` is a P0-era stub, not
   verified against a real CIMET sandbox payload shape.
7. **`CIMET_REAL_CALL`'s `call_date` is a placeholder** (`2026-01-01`,
   recorded in `provenance.call_date` as `"unknown"`) since the supplied
   transcript carries no call metadata — if CIMET provides the real date,
   update `data/cimet/leads_cimet.json` (it may change which check *version*
   resolves, if the checklist ever gets a second version like the synthetic
   `CHK_A_DMO` does).

## Anything I know that isn't written down elsewhere

- **`test_deepgram.py` at the repo root contains a live Deepgram API key in
  plaintext, and it's committed to git** (`git ls-files` confirms it's
  tracked, not gitignored). This is a real, currently-exposed credential —
  rotate the Deepgram key and either delete this file or move the key into
  `.env` before this repo goes anywhere public. `Sadar.m4a` (a 31s real audio
  recording) and `dg_out.json` (its Deepgram transcription output) are
  leftover recon artifacts from early testing of the audio path — they
  predate the discovery that CIMET's actual supplied data has no audio at
  all, and are unrelated to `CIMET_REAL_CALL`. Both are safe to delete if
  you want a cleaner repo, but I left them since removing tracked files
  wasn't asked for.
- **Why the phase plan diverged from `PLAN.md`/`PLAN-BUILDDAY.md`**: those
  documents assume synthetic data throughout and a full 12-hour build-day
  phase sequence (D0–D8). Partway through, real CIMET data arrived — a
  transcript-only broadband sale call, no audio — and the user explicitly
  compressed scope: no more named P3–P7 phases, no D4 threshold tuning, a
  hard 4-hour build window. Everything past P2 in git history was built
  off-plan, phase-by-phase by direct instruction rather than by following
  `PLAN.md`/`PLAN-BUILDDAY.md` verbatim. Don't assume those files describe
  what actually got built — this file does.
- **`resolve_checks()` in `src/engine.py` filters an in-memory list**
  (`load_all_checks()` result), not a DB query, even though `src/gate.py` and
  a real `checks` table both exist now. This was flagged once as a possible
  cleanup and explicitly deferred ("switch to DB query only if asked") — it's
  not a bug, just note it before assuming the checks table is the live
  source of truth.
- **The Gemini quota exhaustion was real and verified**, not a guess:
  `429 RESOURCE_EXHAUSTED`, `limit: 20`, confirmed via multiple direct,
  isolated API probes outside the app code. If a future session considers
  going back to Gemini, know that this key's free tier is capped at 20
  requests/day for `gemini-3.6-flash`, which is far below what scoring all
  14 synthetic + CIMET leads needs in one sitting (the synthetic leads no
  longer need it at all now, but CIMET's 6 calls alone will exhaust it in a
  couple of dev iterations).
- **Groq's rate limit is per-minute-ish and token-based (TPM), not daily** —
  qualitatively different from Gemini's wall. A single large prompt (the
  whole CIMET transcript, ~4.5k tokens) eats more than half of the 8000 TPM
  budget for `openai/gpt-oss-120b` by itself, so don't be surprised by 429s
  on the 2nd+ call in a burst; the retry logic in `_call_llm` already handles
  this correctly, just don't strip it out as "unnecessary complexity" without
  understanding why it's there.
- **`data/cimet/call-transcript-redacted.pdf` is the source-of-truth
  artifact; `.json` next to it is derived**, produced once by
  `scripts/extract_cimet_transcript.py`. If CIMET ever supplies a corrected
  or re-redacted PDF, re-run that script rather than hand-editing the JSON.
