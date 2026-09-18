# PLAN-BUILDDAY.md — Build day, 12 hours, solo

**Activate on build day.** Tell Claude: *"CIMET data has arrived. We're switching
from PLAN.md to PLAN-BUILDDAY.md. Start Phase D0."*

Everything in `PLAN.md` is already built and passing against synthetic data.
Today is **integration plus the CIMET-specific parts**. The synthetic set stays
as regression fixtures — after every adapter change, re-run the synthetic suite
to prove nothing broke.

**Phase protocol still applies. One phase at a time. Stop, report, wait for
`approved`.**

Times assume a 09:00 start. Write the real target times into this file at D0.

| Phase | What | Window |
|---|---|---|
| D0 | Recon — read their data before writing anything | 0:00–0:30 |
| D1 | Adapters + transcription | 0:30–2:00 |
| D2 | Type A on their real checklist | 2:00–3:30 |
| D3 | Type B on their real fields | 3:30–6:00 |
| D4 | Type C + guardrails | 6:00–7:00 |
| D5 | Gate + sandbox submission | 7:00–8:00 |
| D6 | UI on real data | 8:00–9:15 |
| D7 | Accuracy + dashboard | 9:15–10:15 |
| D8 | **FREEZE** — demo, video, slides, README, submit | 10:15–12:00 |

**Hard rule: at 10:15 all feature work stops.** The last approved commit is the
product.

---

## D0 — Recon (no code)

**First action, before reading anything else: start Deepgram on their test
recording.** It takes under a minute and everything downstream depends on it.

```bash
python -m src.transcribe data/cimet/<recording>
```

Then open every supplied file and answer these, writing them into `RECON.md`.

**About the transcript**
1. Word-level timestamps? Turn-level only? None?
2. Speaker separation? What labels?
3. Format: JSON, CSV, plain text, VTT/SRT?
4. If no timings: use the Deepgram output from the command above and align their
   sanitised text to it. Click-to-audio is 20% of the score.

**About the check library**
5. Approved **script text** for verbatim checks? *(If not → we draft it, D2.)*
6. Effective dates / versions? *(If not → we add them and demo the mechanism.)*
7. What do the weights mean — points, or pass thresholds?
8. How many checks, split across the three types?

**About the leads**
9. CRM field values present, under what names?
10. Plan / rate card with actual rates? *(If not → small synthetic one, disclosed.)*
11. Call dates? Agent and TL identifiers?

**About the sandbox**
12. Exact payload shape. Endpoint or file drop? Auth?

**About evaluation**
13. Human-auditor verdicts to measure agreement against? *(If not → hand-label
    5–10 checks yourself in D7. A small honest ground truth beats no number.)*

**Also in the first hour:** find a QA-team mentor and ask *"which checks do your
auditors disagree on most?"* That tells you where the accuracy marks live.

**Done when** `RECON.md` has all 13 answers and the Deepgram transcript is
cached.

---

## D1 — Adapters and transcription

**Build**
- Rewrite `load_checks`, `load_leads`, `load_transcript` against CIMET's formats.
  **Only these files change.** Anything else → stop and tell me.
- Default every field CIMET didn't supply; record it in `provenance`.
- Wire `transcribe.py` to their recording; confirm the cache works.
- If their transcript has no timings, align it to the Deepgram words.
- Load everything into SQLite.

**Done when**
```bash
python -m scripts.load_cimet
python -m scripts.regression_synthetic   # synthetic suite still green
```
CIMET's leads and checks are queryable, at least one lead has usable timestamps,
and `provenance` lists what we supplied.

---

## D2 — Type A on the real checklist

**Build**
- Map CIMET's verbatim criteria to `Check` rows.
- **If no script text supplied:** listen to the test recording and draft approved
  wording for each verbatim check. Mark every one `provenance: drafted_by_us`.
  Say it out loud in the demo — the brief expects drafted scripts as part of the
  build.
- Tune `pass_at` / `fail_at` against the real call: paraphrase must not pass, a
  verbatim read with filler words must not fail.
- Tune `min_word_confidence` against the real ASR confidence distribution.
  Expect most words above 0.95 and misheard ones near 0.30.
- **If the library has no versioning:** add `effective_from` to every check and
  create one deliberate second version, so by-call-date resolution is
  demonstrable.

**Done when** every Type A check runs on the real lead with a correct verdict and
a timestamp that plays the right audio when clicked — and one check demonstrably
resolves to an older version for an older call date.

---

## D3 — Type B on the real fields

Biggest phase. 25% coverage and much of the 30% accuracy sits here.

**Build**
- Point the resolver at CIMET's actual CRM field names and rate-card fields.
- Get the two worked-example checks working: **quoted rate vs plan rate**, and
  **email read back vs CRM field**.
- Extend to the rest of their checklist: address, DOB, NMI/MIRN, fuel type,
  concession, life support, move-in date, gift card value.
- **Spoken numbers are the main risk and it is now a verified one.** Real
  Deepgram output fragments "thirty one point nine cents" into `31` /
  `percent` / `9¢`. Test every form against the real call before trusting the
  comparator.
- Anything below the confidence threshold → `LOW_CONFIDENCE`. Never a silent
  pass on a critical.

**Done when** the real lead produces correct FAILs with expected-vs-actual on
both worked-example checks, and every other Type B check returns a defensible
verdict with evidence.

**If late at 6:00:** ship what works, mark the rest `LOW_CONFIDENCE` with
"extraction not implemented", and move on. Routing the unknown to a human is the
honest behaviour and exactly what the gate criterion rewards.

---

## D4 — Type C and guardrails

**Build**
- Point behaviour checks at the real transcript; tune thresholds so an ordinary
  call doesn't produce noise.
- Confirm the timing-tolerance logic holds on real data — out-of-order spans are
  confirmed to occur, and must never produce phantom dead air.
- Guardrails, all demoable:
  - card-number detection → masked everywhere, violation still flags
  - consent verified as a check, never inferred
  - no auto-correction anywhere — grep and confirm
  - checks resolved by call date
  - overrides logged with actor and reason

**Done when** behaviour checks give sensible non-critical results on a real call,
and each guardrail can be shown on screen in under a minute.

---

## D5 — Gate and sandbox

**Build**
- Run the gate across every CIMET lead.
- Rewrite `map_to_payload` to their real shape; submit to the sandbox.
- Handle success, validation error, and network failure visibly — never a crash.

**Done when** a real lead scores, gates, and submits successfully, and a held
lead correctly does **not** submit.

---

## D6 — UI on real data

The P3 UI exists; this is adapting it.
- Queues populated from real leads
- Click-to-audio against the real recording
- Header: gate status, both scores, check-library version, call date
- Override flow writing and displaying real rows

**Done when** you can, in front of a judge: open a held lead, see why it was
held, click the failing check, hear the twenty seconds that prove it, and
override it with a logged reason.

---

## D7 — Accuracy and dashboard

**Build**
- Run `accuracy.py` against whatever ground truth exists (theirs, or your own
  hand labels from D0/13).
- Two numbers for the slide: **agreement rate** and **false-passes on criticals**
  (target zero).
- Minimal dashboard: first-pass yield, critical fail rate by check, repeat
  offenders.
- The efficiency number: minutes of audit listening per sale today versus seconds
  under this system, computed from the real call length.

**Done when** both numbers are real, from a script you can re-run live, not typed
into a slide.

---

## D8 — FREEZE at 10:15

No new features. None.

- [ ] Verify the demo runs with **wi-fi off** — Deepgram and LLM caches warm
- [ ] Pre-fill the demo lead; no typing during the demo
- [ ] Record a 90-second backup video of the full demo
- [ ] `README.md`: problem, solution, architecture, how to run, what was
      pre-built vs built today, what we drafted ourselves, next steps
- [ ] 5 slides: bottleneck → live demo → how it works → accuracy and efficiency
      numbers → production next steps
- [ ] Rehearse twice, timed
- [ ] Submit repo + demo **30 minutes before the deadline**

---

## Demo script (5 minutes)

1. **The bottleneck (45s).** An auditor listens to a 30-minute call, fills an
   Excel form, and the sale waits. Thousands of sales a month, ~30 retailers. It
   doesn't scale and won't survive a retailer audit.
2. **Live run (2 min).** Score a real lead → held. Show why: rate quoted 28.6,
   plan says 31.9. Click it → the audio plays those seconds. Same for the email
   typo. Then a clean lead → auto-submits, no human touch. Then a low-confidence
   lead → routes to QA rather than passing.
3. **How it works (45s).** One architecture slide. Deterministic verbatim and
   behaviour checks; LLM only for factual extraction, with confidence; ASR
   confidence feeds the verdict; every score resolves to a line, a second, and
   the rule version live on the call date.
4. **The numbers (45s).** Agreement with auditors X%. Zero false-passes on
   criticals. 30 minutes of listening per sale becomes ~20 seconds on flagged
   calls only. First-pass yield Y%.
5. **Next (30s).** Dialler API push, all 30 retailers, calibration loop from the
   5% sample and logged overrides.

**Q&A you will get:** what if the model is wrong (nothing uncertain auto-passes;
5% of clean calls audited anyway; overrides logged and feed calibration) · cost
per call · scaling to 30 retailers · what you'd do with another week · **what you
built today versus beforehand** — answer that plainly and precisely.

---

## Cut order if behind

1. Dashboard beyond first-pass yield
2. Type C beyond dead air
3. Agent and QA views (keep the TL view only)
4. Extra Type B checks beyond the two worked-example ones

**Never cut:** click-to-audio traceability, the gate's four branches, the
guardrails, or the freeze at 10:15.
