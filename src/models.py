"""Internal data model. External formats never appear outside src/adapters/.

See SCHEMA.md for the design principles and rationale behind every field.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

CheckType = Literal["A", "B", "C"]  # verbatim | factual | behaviour
# NOT_APPLICABLE: the check cannot be evaluated with the data supplied (e.g. a
# duration-based check against a no-audio, estimated-timing transcript). On a
# critical check it routes to a human like LOW_CONFIDENCE; on a non-critical
# check it is excluded from scoring and shown as "not evaluable with supplied
# data" -- it must never silently block AUTO_SUBMIT on its own.
Status = Literal["PASS", "FAIL", "LOW_CONFIDENCE", "NOT_APPLICABLE"]
GateStatus = Literal["AUTO_SUBMIT", "HELD", "QA_REVIEW"]


@dataclass
class Word:
    """Mirrors a Deepgram word object."""

    text: str  # lowercase, for matching
    start: float  # seconds
    end: float
    confidence: float = 1.0  # ASR confidence — REAL signal, 0.30-1.0
    speaker: Optional[int] = None
    speaker_confidence: float = 0.0  # often 0.3-0.5 even when correct
    punctuated: str = ""  # for display; falls back to text
    line_number: Optional[int] = None  # source row, for no-audio transcripts

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)  # never negative


@dataclass
class Turn:
    """One utterance. Built from Deepgram's results.utterances[]."""

    speaker: str  # "AGENT" | "CUSTOMER" | "SPK_0" | "UNKNOWN"
    text: str
    start: float
    end: float
    confidence: float = 1.0
    words: list[Word] = field(default_factory=list)
    line_number: Optional[int] = None  # source row, for no-audio transcripts

    @property
    def mean_word_confidence(self) -> float:
        if not self.words:
            return self.confidence
        return sum(w.confidence for w in self.words) / len(self.words)

    @property
    def min_word_confidence(self) -> float:  # drives Type A penalty
        if not self.words:
            return self.confidence
        return min(w.confidence for w in self.words)


@dataclass
class Transcript:
    turns: list[Turn] = field(default_factory=list)
    source: str = "unknown"  # "deepgram" | "cimet_supplied" | "synthetic"
    has_word_timings: bool = False
    has_speakers: bool = False
    audio_duration: float = 0.0

    @property
    def full_text(self) -> str:
        return " ".join(t.text for t in self.sorted_turns())

    @property
    def words(self) -> list[Word]:  # flattened, sorted by start
        all_words = [w for t in self.turns for w in t.words]
        return sorted(all_words, key=lambda w: w.start)

    def window(self, start: float, end: float) -> list[Turn]:
        """Turns whose span overlaps [start, end]."""
        return [t for t in self.sorted_turns() if t.start < end and t.end > start]

    def sorted_turns(self) -> list[Turn]:  # ALWAYS use this, never .turns
        return sorted(self.turns, key=lambda t: t.start)


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
    effective_to: Optional[date] = None  # None = still in force

    # Type A
    expected_script_text: Optional[str] = None
    pass_at: float = 0.85  # similarity >= pass_at -> PASS
    fail_at: float = 0.60  # similarity <= fail_at -> FAIL
    # between            -> LOW_CONFIDENCE
    min_word_confidence: float = 0.55  # below this in the matched span,
    # downgrade a PASS to LOW_CONFIDENCE

    # Type B
    crm_field: Optional[str] = None
    plan_field: Optional[str] = None
    comparator: Optional[str] = None  # email|rate|currency|date|phone|address|text
    tolerance: float = 0.0  # numeric comparators

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
    detail: str = ""  # short human reason, shown in the UI
    asr_confidence: Optional[float] = None  # min word conf in matched span
    # No-audio (estimated) timing: mutually exclusive with start_ts/end_ts.
    # Populated instead of start_ts/end_ts when the source transcript has no
    # measured timing -- never both, so a UI can't mistake one for the other.
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
