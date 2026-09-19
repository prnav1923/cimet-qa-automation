# SYNTHETIC-DATA.md — Dummy data spec

Generated in pre-build Phase P1. Everything here is fabricated. No real PII, no
real retailers, no real customers. On build day this is replaced by CIMET's data
and kept as regression fixtures.

Shapes mirror what CIMET said they'll hand over: a synthetic lead dataset
(ID, retailer, last-completed step, test contact, sanitised transcript), a
check-library export for one retailer (criteria, weights, critical flags), and a
scoring sandbox payload shape.

CIMET did **not** promise: approved script text, effective dates, or plan/rate
values. Our synthetic set includes all three so the engine is built to use them.
If CIMET's real data lacks them we draft them on the day and record it in
`provenance`.

**Transcripts must imitate real Deepgram output**, including its flaws — verified
in a live test run and listed below.

---

## Files to generate

```
data/synthetic/
├── checks_retailer1.json     # 14 checks (15 rows, DMO has 2 versions)
├── leads.json                # 12 leads
├── transcripts/LEAD_*.json   # one per lead, Deepgram-shaped
├── transcripts/LEAD_NOTS.txt # one plain-text, no timings (fallback path)
├── rate_card.json            # 4 plans
├── auditor_labels.json       # human verdicts for 6 leads
├── expected_outcomes.json    # the engine's test oracle
├── payload_shape.json        # mock sandbox contract
└── audio/LEAD_*.mp3          # silent placeholders, correct durations
```

---

## 1. Check library — `checks_retailer1.json`

Retailer `RTL_001`, "Aurora Energy" (invented). 14 checks.

**Type A — verbatim (5)**

| check_id | description | critical | expected_script_text |
|---|---|---|---|
| `CHK_A_DISCLAIMER` | Recording disclaimer read | yes | "This call is being recorded for quality and compliance purposes." |
| `CHK_A_ACCOUNT_HOLDER` | Account holder confirmed | yes | "Can I confirm I'm speaking with the account holder listed on the bill?" |
| `CHK_A_DMO` | DMO reference price read verbatim | yes | "This plan's estimated annual cost is compared against the Default Market Offer set by the Australian Energy Regulator for your distribution zone." |
| `CHK_A_COOLING_OFF` | Cooling-off rights stated | yes | "You have a ten business day cooling-off period during which you can cancel this agreement at no cost." |
| `CHK_A_TERMS` | T&Cs delivery explained | no | "We'll email you the full terms and conditions along with your welcome pack." |

**Type B — factual (6, all critical)**

| check_id | description | crm_field | plan_field | comparator | tolerance |
|---|---|---|---|---|---|
| `CHK_B_PEAK_RATE` | Peak rate quoted matches plan | — | `peak_rate_c_per_kwh` | `rate` | 0.05 |
| `CHK_B_DAILY_SUPPLY` | Daily supply charge matches plan | — | `daily_supply_c` | `rate` | 0.05 |
| `CHK_B_EMAIL` | Email read back matches CRM | `email` | — | `email` | 0 |
| `CHK_B_ADDRESS` | Supply address matches CRM | `supply_address` | — | `address` | 0 |
| `CHK_B_DOB` | DOB confirmed matches CRM | `dob` | — | `date` | 0 |
| `CHK_B_NMI` | NMI confirmed matches CRM | `nmi` | — | `text` | 0 |

**Type C — behaviour (3, none critical)**

| check_id | description | params |
|---|---|---|
| `CHK_C_DEAD_AIR` | No dead air over 30s | `{"max_dead_air_s": 30}` |
| `CHK_C_INTERRUPTIONS` | Agent interruptions under 5 | `{"max_interruptions": 5}` |
| `CHK_C_TALK_RATIO` | Agent talk ratio under 75% | `{"max_agent_talk_ratio": 0.75}` |

**Versioning — include a real version change.** `CHK_A_DMO` has two rows:
- v1, `effective_from` 2025-01-01, `effective_to` 2026-07-01, shorter wording
- v2, `effective_from` 2026-07-01, `effective_to` null, the wording above

At least two leads have call dates **before** 2026-07-01 so an old call can be
correctly scored against old wording.

Weights: criticals 3.0, non-criticals 1.0.

```json
{
  "retailer_id": "RTL_001",
  "retailer_name": "Aurora Energy",
  "checks": [
    {
      "check_id": "CHK_A_DISCLAIMER", "version": 1, "type": "A",
      "description": "Recording disclaimer read",
      "is_critical": true, "weight": 3.0,
      "effective_from": "2025-01-01", "effective_to": null,
      "expected_script_text": "This call is being recorded for quality and compliance purposes.",
      "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55
    }
  ]
}
```

---

## 2. Rate card — `rate_card.json`

| plan_id | name | peak_rate_c_per_kwh | daily_supply_c | discount_pct |
|---|---|---|---|---|
| `PLAN_A` | Aurora Saver | 31.9 | 98.5 | 0 |
| `PLAN_B` | Aurora Flex | 28.6 | 104.2 | 5 |
| `PLAN_C` | Aurora Green | 34.1 | 96.0 | 0 |
| `PLAN_D` | Aurora Fixed 12 | 30.2 | 101.7 | 3 |

`PLAN_A` and `PLAN_B` use the exact numbers from CIMET's worked example
(31.9 vs 28.6), so the "agent quoted the wrong plan's rate" failure is
reproducible.

---

## 3. Leads — `leads.json`

12 leads on `RTL_001`, 4 agents, 2 TLs, campaigns across owned site, affiliate,
paid search, inbound. Test contacts only (`+61 4XX XXX XXX`, `@example.com`).

```json
{
  "lead_id": "LEAD_3613790",
  "retailer_id": "RTL_001",
  "call_date": "2026-09-02",
  "agent_id": "AGT_A",
  "team_lead_id": "TL_1",
  "campaign": "affiliate",
  "last_completed_step": "plan_selection",
  "recording_path": "data/synthetic/audio/LEAD_3613790.mp3",
  "plan_id": "PLAN_A",
  "crm_fields": {
    "email": "j.smith@example.com",
    "supply_address": "12 Rundle Street, Adelaide SA 5000",
    "dob": "1984-03-17",
    "nmi": "2001234567",
    "fuel_type": "electricity",
    "concession": false,
    "life_support": false,
    "move_in_date": "2026-09-15"
  }
}
```

**Required scenario spread** — every code path must be exercised:

| # | Lead | Scenario | Expected gate |
|---|---|---|---|
| 1 | `LEAD_3613790` | Worked example: rate mismatch (said 28.6, plan 31.9) + email typo (`gmial`) + 47s dead air | HELD |
| 2 | — | Fully clean, all green, high confidence | AUTO_SUBMIT |
| 3 | — | Clean **and** in the deterministic 5% sample | AUTO_SUBMIT + sampled |
| 4 | — | Mumbled DMO, similarity ~0.72 | QA_REVIEW |
| 5 | — | Disclaimer never read | HELD |
| 6 | — | Old call (2026-05-10), scored against DMO **v1**, passes | AUTO_SUBMIT |
| 7 | — | Old call reading the *new* wording, so fails v1 | HELD |
| 8 | — | Card number spoken mid-call → redaction path, violation flags | HELD |
| 9 | — | Address differs only as "St" vs "Street" → must normalise to PASS | AUTO_SUBMIT |
| 10 | — | DOB mismatch, clear fail | HELD |
| 11 | — | Heavy crosstalk, 9 interruptions, non-critical only | AUTO_SUBMIT |
| 12 | — | Correct rate quoted, but for the wrong plan on the lead | HELD |

**Two extra cases driven by the real Deepgram test — add these:**

| # | Scenario | Expected |
|---|---|---|
| 13 | **Fragmented rate.** The rate appears as separate tokens `"31"` / `"percent"` / `"9¢"` (exactly what Deepgram returned live for "thirty one point nine cents"). The comparator must reassemble to 31.9 and PASS. | AUTO_SUBMIT |
| 14 | **Unreassemblable rate.** Tokens too garbled to resolve confidently. | QA_REVIEW |

Lead 9 proves comparators normalise rather than string-compare. Lead 13 proves
they survive real ASR fragmentation. Both are where false criticals come from.

---

## 4. Transcripts — `transcripts/LEAD_*.json`

**Deepgram-shaped**, 60–90 turns, 20–30 minutes of call time.

```json
{
  "lead_id": "LEAD_3613790",
  "source": "synthetic",
  "has_word_timings": true,
  "has_speakers": true,
  "audio_duration": 1834.2,
  "turns": [
    {
      "speaker": "SPK_0", "text": "This call is being recorded for quality and compliance purposes.",
      "start": 12.4, "end": 16.1, "confidence": 0.94,
      "words": [
        {"text": "this", "punctuated": "This", "start": 12.4, "end": 12.6,
         "confidence": 0.98, "speaker": 0, "speaker_confidence": 0.51}
      ]
    }
  ]
}
```

**Realism requirements — these come from a verified live Deepgram run, not
guesswork:**

1. **Per-word confidence must vary realistically.** Most words 0.95–1.0, with
   occasional dips to 0.30–0.70 on mumbled or unusual words. At least one
   verbatim check in one lead must contain a word below 0.55, so the ASR-penalty
   path is exercised.
2. **`speaker_confidence` stays low**, 0.28–0.58, even where the speaker label is
   right. Nothing critical may depend on the label alone.
3. **Some timestamps overlap or run out of order.** Include at least one pair
   like `end: 14.24` followed by `start: 13.515`. The engine must handle it
   without producing negative durations or phantom dead air.
4. **Numbers fragment.** Spoken rates appear as multiple tokens
   (`"31"`, `"percent"`, `"9¢"`), never as a clean `"31.9"`.
5. Filler words, false starts, self-corrections.
6. One mishear-and-repeat exchange.
7. Overlapping turns for the interruption check.
8. One long silence for dead air.
9. One lead where a required line is **paraphrased** rather than read verbatim —
   the most interesting case.

**Plus one plain-text transcript** (`LEAD_NOTS.txt`, no timings, no speakers) to
prove the fallback path: transcribe the audio with Deepgram and align.

---

## 5. Auditor labels — `auditor_labels.json`

Verdicts for 6 of the 12 leads.

```json
[{"lead_id": "LEAD_3613790", "check_id": "CHK_B_PEAK_RATE",
  "status": "FAIL", "auditor_id": "AUD_1"}]
```

Include **one deliberate disagreement** where the human passed something the
engine fails. That makes the agreement metric interesting and gives you
something honest to say about calibration.

---

## 6. Payload shape — `payload_shape.json`

Mock of the sandbox contract, replaced on build day.

```json
{
  "lead_id": "LEAD_3613790", "retailer_id": "RTL_001",
  "scored_at": "2026-09-19T14:02:11Z", "gate_status": "HELD",
  "score_with_fatals": 0.0, "score_without_fatals": 0.82,
  "check_library_version": "2026-07-01",
  "results": [
    {
      "check_id": "CHK_B_PEAK_RATE", "check_version": 1,
      "status": "FAIL", "confidence": 0.94, "is_critical": true,
      "evidence": {
        "transcript_line": "so your peak rate there is twenty eight point six cents",
        "start_ts": 842.0, "end_ts": 846.5, "asr_confidence": 0.91
      },
      "expected": "31.9", "actual": "28.6"
    }
  ]
}
```

---

## 7. `expected_outcomes.json`

The test oracle for the whole engine: for each of the 14 leads, the expected gate
status, whether it's sampled, and the expected status of every critical check.
`python -m src.gate --all` compares against this file. That comparison **is** the
P4 pass/fail test.

---

## Generation rules

- One script, `scripts/generate_synthetic.py`, writes every file.
  `random.seed(42)` so regeneration is byte-identical.
- Timings internally consistent apart from the deliberate messiness above; word
  timings inside turn bounds except where an overlap is intentional.
- Silent MP3 placeholders via pydub, durations matching each transcript.
- No real names, addresses, emails, phone numbers, or retailer names anywhere.
