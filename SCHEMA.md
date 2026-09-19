# SCHEMA.md — Data model

Internal model only. External formats never appear outside `src/adapters/`.

## Design principles

1. **Tolerant.** Every optional field has a default; a missing source column
   never crashes a loader.
2. **Lossless.** `raw: dict` keeps the untouched source record.
3. **Honest.** `provenance` records what we supplied ourselves versus what CIMET
   supplied. The demo says this out loud.
4. **Traceable.** Every result carries a transcript line, a timestamp, and the
   check version that produced it.
5. **Defensive about timings.** Real transcripts have overlapping and
   out-of-order spans (verified in a live Deepgram run). Never assume a clean
   monotonic sequence.

---

## Dataclasses (`src/models.py`)

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

CheckType  = Literal["A", "B", "C"]          # verbatim | factual | behaviour
Status     = Literal["PASS", "FAIL", "LOW_CONFIDENCE", "NOT_APPLICABLE"]
GateStatus = Literal["AUTO_SUBMIT", "HELD", "QA_REVIEW"]


@dataclass
class Word:
    """Mirrors a Deepgram word object."""
    text: str                         # lowercase, for matching
    start: float                      # seconds
    end: float
    confidence: float = 1.0           # ASR confidence — REAL signal, 0.30-1.0
    speaker: Optional[int] = None
    speaker_confidence: float = 0.0   # often 0.3-0.5 even when correct
    punctuated: str = ""              # for display; falls back to text

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)   # never negative


@dataclass
class Turn:
    """One utterance. Built from Deepgram's results.utterances[]."""
    speaker: str                      # "AGENT" | "CUSTOMER" | "SPK_0" | "UNKNOWN"
    text: str
    start: float
    end: float
    confidence: float = 1.0
    words: list[Word] = field(default_factory=list)

    @property
    def mean_word_confidence(self) -> float: ...
    @property
    def min_word_confidence(self) -> float: ...   # drives Type A penalty


@dataclass
class Transcript:
    turns: list[Turn] = field(default_factory=list)
    source: str = "unknown"           # "deepgram" | "cimet_supplied" | "synthetic"
    has_word_timings: bool = False
    has_speakers: bool = False
    audio_duration: float = 0.0

    @property
    def full_text(self) -> str: ...
    @property
    def words(self) -> list[Word]: ...            # flattened, sorted by start
    def window(self, start: float, end: float) -> list[Turn]: ...
    def sorted_turns(self) -> list[Turn]: ...     # ALWAYS use this, never .turns
```

**Timing rules — enforce in code, not by assumption:**
- `sorted_turns()` sorts by `start`; all gap/overlap logic uses it.
- A gap is `max(0.0, next.start - current.end)`. Negative means overlap, which
  counts as an interruption, never as negative dead air.
- `words` is flattened and re-sorted, because word order within a response is
  not guaranteed monotonic.

```python
@dataclass
class Check:
    check_id: str
    retailer_id: str
    type: CheckType
    description: str
    is_critical: bool = False
    weight: float = 1.0
    version: int = 1
    effective_from: date = date(1970, 1, 1)
    effective_to: Optional[date] = None      # None = still in force

    # Type A
    expected_script_text: Optional[str] = None
    pass_at: float = 0.85             # similarity >= pass_at -> PASS
    fail_at: float = 0.60             # similarity <= fail_at -> FAIL
                                      # between            -> LOW_CONFIDENCE
    min_word_confidence: float = 0.55 # below this in the matched span,
                                      # downgrade a PASS to LOW_CONFIDENCE

    # Type B
    crm_field: Optional[str] = None
    plan_field: Optional[str] = None
    comparator: Optional[str] = None  # email|rate|currency|date|phone|address|text
    tolerance: float = 0.0            # numeric comparators

    # Type C
    params: dict[str, Any] = field(default_factory=dict)

    raw: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class Lead:
    lead_id: str
    retailer_id: str
    call_date: date
    agent_id: str = "UNKNOWN"
    campaign: str = "UNKNOWN"
    team_lead_id: str = "UNKNOWN"
    recording_path: Optional[str] = None
    transcript: Optional[Transcript] = None
    crm_fields: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class CheckResult:
    lead_id: str
    check_id: str
    check_version: int
    status: Status
    confidence: float
    is_critical: bool
    weight: float
    transcript_line: str = ""
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    detail: str = ""                  # short human reason, shown in the UI
    asr_confidence: Optional[float] = None   # min word conf in matched span
    # No-audio (estimated) timing -- mutually exclusive with start_ts/end_ts.
    # Populated instead of them when the source transcript has no measured
    # timing, so a UI can never mistake an estimate for a measurement.
    line_number: Optional[int] = None
    estimated_ts: Optional[float] = None
    estimated_end_ts: Optional[float] = None
    scored_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Decision:
    lead_id: str
    gate_status: GateStatus
    reason: str
    sampled: bool = False
    score_with_fatals: float = 0.0
    score_without_fatals: float = 0.0
    decided_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Override:
    lead_id: str
    check_id: str
    actor: str
    old_status: Status
    new_status: Status
    reason: str
    created_at: datetime = field(default_factory=datetime.utcnow)
```

---

## Deepgram → Transcript mapping

`src/adapters/load_transcript.py`:

```
results.utterances[]  →  Turn
    .start, .end, .confidence, .transcript → text
    .speaker (int)    →  "SPK_{n}", mapped to AGENT/CUSTOMER later
    .words[]          →  Word
        .word              → Word.text
        .punctuated_word   → Word.punctuated
        .start .end        → Word.start/.end
        .confidence        → Word.confidence
        .speaker           → Word.speaker
        .speaker_confidence→ Word.speaker_confidence
```

If `utterances` is absent, fall back to
`results.channels[0].alternatives[0].words` and segment on speaker change or a
gap over 0.8s.

**Speaker role assignment:** the speaker who says the recording disclaimer is the
AGENT; the other is the CUSTOMER. If that can't be determined, label them
`SPK_0`/`SPK_1` and never let a critical check depend on the label.

---

## SQLite schema (`src/db.py`)

```sql
CREATE TABLE IF NOT EXISTS checks (
    check_id             TEXT NOT NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    retailer_id          TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('A','B','C')),
    description          TEXT NOT NULL,
    is_critical          INTEGER NOT NULL DEFAULT 0,
    weight               REAL NOT NULL DEFAULT 1.0,
    effective_from       TEXT NOT NULL DEFAULT '1970-01-01',
    effective_to         TEXT,
    expected_script_text TEXT,
    pass_at              REAL DEFAULT 0.85,
    fail_at              REAL DEFAULT 0.60,
    min_word_confidence  REAL DEFAULT 0.55,
    crm_field            TEXT,
    plan_field           TEXT,
    comparator           TEXT,
    tolerance            REAL DEFAULT 0.0,
    params_json          TEXT DEFAULT '{}',
    raw_json             TEXT DEFAULT '{}',
    provenance_json      TEXT DEFAULT '{}',
    PRIMARY KEY (check_id, version)
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id         TEXT PRIMARY KEY,
    retailer_id     TEXT NOT NULL,
    call_date       TEXT NOT NULL,
    agent_id        TEXT,
    campaign        TEXT,
    team_lead_id    TEXT,
    recording_path  TEXT,
    transcript_json TEXT,
    crm_fields_json TEXT DEFAULT '{}',
    plan_json       TEXT DEFAULT '{}',
    raw_json        TEXT DEFAULT '{}',
    provenance_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS check_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         TEXT NOT NULL,
    check_id        TEXT NOT NULL,
    check_version   INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PASS','FAIL','LOW_CONFIDENCE')),
    confidence      REAL NOT NULL,
    is_critical     INTEGER NOT NULL,
    weight          REAL NOT NULL,
    transcript_line TEXT,
    start_ts        REAL,
    end_ts          REAL,
    expected        TEXT,
    actual          TEXT,
    detail          TEXT,
    asr_confidence  REAL,
    scored_at       TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_results_lead ON check_results(lead_id);

CREATE TABLE IF NOT EXISTS decisions (
    lead_id              TEXT PRIMARY KEY,
    gate_status          TEXT NOT NULL
                         CHECK (gate_status IN ('AUTO_SUBMIT','HELD','QA_REVIEW')),
    reason               TEXT,
    sampled              INTEGER NOT NULL DEFAULT 0,
    score_with_fatals    REAL,
    score_without_fatals REAL,
    decided_at           TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
);

CREATE TABLE IF NOT EXISTS overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     TEXT NOT NULL,
    check_id    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    old_status  TEXT NOT NULL,
    new_status  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditor_labels (
    lead_id    TEXT NOT NULL,
    check_id   TEXT NOT NULL,
    status     TEXT NOT NULL,
    auditor_id TEXT,
    PRIMARY KEY (lead_id, check_id, auditor_id)
);

CREATE TABLE IF NOT EXISTS llm_cache (
    input_hash    TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
```

---

## Version resolution

```python
def resolve_checks(retailer_id: str, call_date: date) -> list[Check]:
    """Checks in force on the call date. Never 'today's version'."""
```

```sql
SELECT * FROM checks
WHERE retailer_id = ?
  AND effective_from <= ?
  AND (effective_to IS NULL OR effective_to > ?)
```

---

## Gate logic

```python
def gate(results: list[CheckResult], lead_id: str) -> Decision:
    # NOT_APPLICABLE on a critical check is treated exactly like a critical
    # FAIL -- it's data we can't evaluate, not data that passed. Non-critical
    # NOT_APPLICABLE results are excluded from scoring entirely upstream (in
    # score_lead/the two-score calculation) and never reach this function.
    if any(r.is_critical and r.status in ("FAIL", "NOT_APPLICABLE") for r in results):
        return Decision(..., gate_status="HELD", ...)
    if any(r.status == "LOW_CONFIDENCE" for r in results):
        return Decision(..., gate_status="QA_REVIEW", ...)
    return Decision(..., gate_status="AUTO_SUBMIT",
                    sampled=is_sampled(lead_id))


def is_sampled(lead_id: str, rate_pct: int = 5) -> bool:
    """Deterministic 5% sample. Never random — the demo must reproduce."""
    h = hashlib.md5(lead_id.encode()).hexdigest()
    return int(h, 16) % 100 < rate_pct
```

A sampled lead still auto-submits; it also appears in the QA sample list.

## Two scores

```
score_without_fatals = weighted % of non-critical checks passed
score_with_fatals    = 0 if any critical failed, else score_without_fatals
```
