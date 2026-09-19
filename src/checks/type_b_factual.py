"""Type B -- factual checks. Two extraction paths, chosen per check_id:

- Deterministic regex (the six synthetic ground-truth checks --
  CHK_B_PEAK_RATE/DAILY_SUPPLY/EMAIL/ADDRESS/DOB/NMI): the synthetic
  transcript generator's agent-script wording is fixed and known, so the
  value is always the turn right after a fixed anchor sentence. No API call,
  no quota, no network -- see `_ANCHORS` and `_score_ground_truth_regex`.
- LLM extraction (CIMET's real, unscripted checklist -- the "consistency"
  comparator, and any other check with no deterministic anchor): strict JSON
  {field, spoken_value, transcript_line, line_number, confidence}, cached by
  input hash in the llm_cache table so a re-run makes zero repeat API calls.

Both paths feed the same `_values_match` comparator, so the comparison logic
itself never differs by extraction method.

Nothing uncertain auto-passes: missing extraction, low confidence, or no
GROQ_API_KEY configured all return LOW_CONFIDENCE, never a silent PASS.

Provider: Groq (OpenAI-compatible chat completions endpoint), called over
plain REST with `requests` -- no SDK, same reasoning as Deepgram in
CLAUDE.md. Switched from Gemini after repeatedly hitting its free-tier
quota wall (20 requests/day); model is `openai/gpt-oss-120b` -- Groq's
account for this key has no `llama-3.3-70b-versatile` (confirmed via
GET /v1/models, not guessed). Everything above and below _call_llm
(prompting, caching, comparators) is provider-agnostic; swapping providers
again means only touching that one function.
"""

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import date

import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv

from src.db import get_llm_cache, set_llm_cache
from src.models import Check, CheckResult, Lead, Transcript

load_dotenv()

GROQ_MODEL = "openai/gpt-oss-120b"  # confirmed available via GET /v1/models for this key
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MIN_EXTRACTION_CONFIDENCE = 0.5


def _numbered_transcript(transcript: Transcript) -> str:
    lines = []
    for i, turn in enumerate(transcript.sorted_turns(), start=1):
        lines.append(f"{i}. {turn.speaker}: {turn.text}")
    return "\n".join(lines)


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def _call_llm(conn: sqlite3.Connection, prompt: str) -> dict | None:
    """Returns the parsed JSON extraction, or None if unavailable (no key,
    API error, or a non-JSON response) -- caller must treat None as
    LOW_CONFIDENCE, never guess."""
    key = _cache_key(prompt)
    cached = get_llm_cache(conn, key)
    if cached:
        return json.loads(cached["response_json"])

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    # Groq's 8000 TPM cap on this model is smaller than this prompt's ~4.5k
    # tokens, so two calls back-to-back reliably collide with it -- but it's
    # a rolling window that recovers in under a second once the oldest
    # tokens age out (unlike Gemini's daily wall), and the 429 body names
    # the exact wait. Retry on that specific signal; anything else still
    # fails through to LOW_CONFIDENCE immediately, same as before.
    for attempt in range(6):
        try:
            response = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
        except requests.exceptions.RequestException:
            return None

        if response.status_code == 429:
            wait_match = re.search(r"try again in ([\d.]+)(ms|s)\b", response.text)
            if wait_match:
                raw, unit = float(wait_match.group(1)), wait_match.group(2)
                wait_s = (raw / 1000.0 if unit == "ms" else raw) + 0.25
            else:
                wait_s = 2.0
            time.sleep(min(wait_s, 25.0))
            continue

        try:
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            data = json.loads(text)
        except Exception:
            return None

        set_llm_cache(conn, key, json.dumps(data))
        return data

    return None


def _extract_prompt(field_description: str, transcript: Transcript) -> str:
    return f"""You are extracting one fact from a sales call transcript for QA purposes.

Transcript (numbered turns, speaker: text):
{_numbered_transcript(transcript)}

Find where the call states: {field_description}

Return ONLY strict JSON, no other text, no markdown fences:
{{"field": "<short name for what you found>", "spoken_value": "<the value NORMALISED to plain digits, e.g. 42.90 not 'forty two dollars and ninety' -- comparisons downstream are numeric, so spelled-out numbers cannot be compared; use null if not found>", "transcript_line": "<the exact sentence it appears in, quoted as actually written/spoken, disfluencies and all>", "line_number": <the numbered turn it appears in, as an integer>, "confidence": <0.0 to 1.0>}}
"""


def _parse_number(value) -> float | None:
    if value is None:
        return None
    s = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(match.group(0)) if match else None


def _normalise_address(value: str) -> str:
    s = value.lower().strip()
    s = re.sub(r"[.,]", "", s)
    replacements = {" street": " st", " road": " rd", " avenue": " ave"}
    for long, short in replacements.items():
        s = s.replace(long, short)
    return re.sub(r"\s+", " ", s)


def _values_match(comparator: str, spoken, reference, tolerance: float) -> bool:
    if spoken is None or reference is None:
        return False
    if comparator in ("rate", "currency"):
        s, r = _parse_number(spoken), _parse_number(reference)
        return s is not None and r is not None and abs(s - r) <= (tolerance or 0.0)
    if comparator == "email":
        return str(spoken).strip().lower() == str(reference).strip().lower()
    if comparator == "address":
        return _normalise_address(str(spoken)) == _normalise_address(str(reference))
    if comparator == "date":
        try:
            return date_parser.parse(str(spoken)).date() == (
                reference if isinstance(reference, date) else date_parser.parse(str(reference)).date()
            )
        except (ValueError, OverflowError):
            return False
    if comparator == "phone":
        return re.sub(r"\D", "", str(spoken)) == re.sub(r"\D", "", str(reference))
    # "text" and anything else: exact, case-insensitive
    return str(spoken).strip().lower() == str(reference).strip().lower()



# ---------------------------------------------------------------------------
# Deterministic (no-LLM) extraction for the synthetic ground-truth checks.
#
# These six checks (CHK_B_PEAK_RATE/DAILY_SUPPLY/EMAIL/ADDRESS/DOB/NMI) exist
# only against the synthetic transcript generator, whose agent script wording
# is fixed and known -- so the value is always the turn immediately following
# a fixed anchor sentence. That makes regex extraction reliable here in a way
# it can never be against CIMET's real, unscripted call (which is why that
# path still goes through the LLM, below). Every parsed value is still run
# through the existing `_values_match` comparator -- this only replaces the
# LLM extraction step, not the comparison logic.
# ---------------------------------------------------------------------------

_ANCHORS = {
    "CHK_B_PEAK_RATE": ("So your peak usage rate on this plan works out to", "cents"),
    "CHK_B_DAILY_SUPPLY": ("And the daily supply charge is", "cents"),
    "CHK_B_EMAIL": ("Can I just read back your email to confirm we've got it right?", "email"),
    "CHK_B_ADDRESS": ("Can you confirm the supply address for me?", "address"),
    "CHK_B_DOB": ("And just for security, can I get your date of birth?", "dob"),
    "CHK_B_NMI": ("I've got your NMI here as well", "nmi"),
}

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_WORDS = set(_ONES) | set(_TENS) | {"hundred", "and"}

_ORDINAL_DAY = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "twenty first": 21, "twenty second": 22, "twenty third": 23,
    "twenty fourth": 24, "twenty fifth": 25, "twenty sixth": 26,
    "twenty seventh": 27, "twenty eighth": 28, "twenty ninth": 29,
    "thirtieth": 30, "thirty first": 31,
}
_ADDRESS_FILLER = {"yep", "yeah", "sure", "yes", "that's", "thats"}


def _cardinal_value(tokens: list[str]) -> int | None:
    """Standard word-number folding: 'one hundred and four' -> 104. Returns
    None on any unrecognised token, so callers never guess a wrong number."""
    current, matched = 0, False
    for tok in tokens:
        t = tok.lower()
        if t == "and":
            continue
        if t in _ONES:
            current += _ONES[t]
            matched = True
        elif t in _TENS:
            current += _TENS[t]
            matched = True
        elif t == "hundred":
            current = (current or 1) * 100
            matched = True
        else:
            return None
    return current if matched else None


def _replace_number_words(text: str) -> str:
    """Replaces every maximal run of consecutive number-words with its
    digit value, leaving everything else (including punctuation) untouched."""
    tokens = text.split()
    out: list[str] = []
    run: list[str] = []

    def flush():
        if run:
            val = _cardinal_value(run)
            out.append(str(val) if val is not None else " ".join(run))
            run.clear()

    for tok in tokens:
        bare = tok.strip(".,").lower()
        if bare in _NUMBER_WORDS:
            run.append(bare)
        else:
            flush()
            out.append(tok)
    flush()
    return " ".join(out)


def _turn_after(transcript: Transcript, anchor_substr: str):
    """Returns (anchor_turn, next_turn), or (None, None) if the anchor
    sentence doesn't appear -- caller must treat that as LOW_CONFIDENCE,
    never guess which turn holds the value."""
    turns = transcript.sorted_turns()
    for i, t in enumerate(turns):
        if anchor_substr in t.text:
            if i + 1 < len(turns):
                return t, turns[i + 1]
            return t, None
    return None, None


def _parse_cents_value(text: str) -> float | None:
    """Handles all three synthetic rate-quote shapes: spelled-out
    ('twenty eight point six cents...'), fragmented-but-reassemblable ASR
    tokens ('31 percent 9¢ per...', the real observed Deepgram quirk from
    CLAUDE.md), and fragmented-and-garbled ('thirty one ish cents or
    something', deliberately unparseable). Returns None for the last case --
    never a guessed number."""
    fragment = re.search(r"(\d+)\s*percent\s*(\d+)\s*¢", text)
    if fragment:
        return float(f"{fragment.group(1)}.{fragment.group(2)}")

    normalised = _replace_number_words(text)
    with_point = re.search(r"(\d+)\s*point\s*(\d+)", normalised)
    if with_point:
        return float(f"{with_point.group(1)}.{with_point.group(2)}")

    plain = re.search(r"(\d+)\s*cents?\b", normalised)
    if plain:
        return float(plain.group(1))

    return None


def _parse_email(text: str) -> str:
    s = text.lower().split(", is that right")[0]
    s = re.sub(r"\bdot\b", ".", s)
    s = re.sub(r"\bat\b", "@", s)
    s = re.sub(r"\s+", "", s)
    return s.strip(".,? ")


def _prep_spoken_address(text: str) -> str:
    """Converts the spoken house number and state name into the same form
    the CRM record uses; punctuation/St-vs-Street normalisation is left to
    the existing `_normalise_address` comparator, not duplicated here."""
    s = _replace_number_words(text)
    s = re.sub(r"\bsouth australia\b", "SA", s, flags=re.IGNORECASE)
    tokens = s.split()
    while tokens and tokens[0].strip(".,").lower() in _ADDRESS_FILLER:
        tokens.pop(0)
    return " ".join(tokens)


def _parse_dob_words(text: str) -> str | None:
    """'The seventeenth of March, nineteen eighty four.' -> '17 March 1984',
    a string the existing date comparator can hand straight to dateutil.
    Returns None on anything that doesn't match the expected shape."""
    s = text.lower().strip().rstrip(".")
    if s.startswith("the "):
        s = s[4:]
    if " of " not in s or "," not in s:
        return None
    day_part, rest = s.split(" of ", 1)
    day = _ORDINAL_DAY.get(day_part.strip())
    if day is None:
        return None
    month_part, year_part = rest.split(",", 1)
    month = month_part.strip().title()
    year_tokens = year_part.strip().split()
    if not year_tokens or year_tokens[0] != "nineteen":
        return None
    remainder = _cardinal_value(year_tokens[1:]) if len(year_tokens) > 1 else 0
    if remainder is None:
        return None
    return f"{day} {month} {1900 + remainder}"


def _timing_fields_from_turn(transcript: Transcript, turn) -> dict:
    if transcript.has_word_timings:
        return {"start_ts": turn.start, "end_ts": turn.end}
    return {
        "line_number": turn.line_number,
        "estimated_ts": turn.start, "estimated_end_ts": turn.end,
    }


def _score_ground_truth_regex(check: Check, lead: Lead, base: dict) -> CheckResult:
    reference = None
    if check.crm_field:
        reference = lead.crm_fields.get(check.crm_field)
    elif check.plan_field:
        reference = lead.plan.get(check.plan_field)

    anchor_text, kind = _ANCHORS[check.check_id]
    _, value_turn = _turn_after(lead.transcript, anchor_text)
    if value_turn is None:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=0.0,
            detail=f"Could not locate the transcript turn following '{anchor_text}'.",
        )

    raw_text = value_turn.text
    if kind == "cents":
        spoken = _parse_cents_value(raw_text)
    elif kind == "email":
        spoken = _parse_email(raw_text)
    elif kind == "address":
        spoken = _prep_spoken_address(raw_text)
    elif kind == "dob":
        spoken = _parse_dob_words(raw_text)
    else:  # nmi
        spoken = raw_text.strip()

    timing = _timing_fields_from_turn(lead.transcript, value_turn)

    if spoken is None:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=0.4,
            transcript_line=raw_text,
            expected=str(reference) if reference is not None else None, actual=None,
            detail="Deterministic extraction could not confidently parse this value -- not a silent pass.",
            **timing,
        )

    match = _values_match(check.comparator, spoken, reference, check.tolerance)
    return CheckResult(
        **base, status=("PASS" if match else "FAIL"), confidence=0.99,
        transcript_line=raw_text,
        expected=str(reference), actual=str(spoken),
        detail=f"Regex-extracted '{spoken}' vs reference '{reference}'.",
        **timing,
    )


def _timing_fields(transcript: Transcript, line_number) -> dict:
    """Maps an extracted 1-based turn index back to evidence timing --
    start_ts/end_ts if the source transcript has real measured timing,
    line_number/estimated_ts/estimated_end_ts if it doesn't. Same
    mutually-exclusive pattern as type_a_verbatim.py."""
    if not line_number:
        return {}
    turns = transcript.sorted_turns()
    idx = int(line_number) - 1
    if idx < 0 or idx >= len(turns):
        return {}
    turn = turns[idx]
    if transcript.has_word_timings:
        return {"start_ts": turn.start, "end_ts": turn.end}
    return {
        "line_number": turn.line_number or int(line_number),
        "estimated_ts": turn.start, "estimated_end_ts": turn.end,
    }


def score_type_b(check: Check, lead: Lead, conn: sqlite3.Connection) -> CheckResult:
    base = dict(
        lead_id=lead.lead_id, check_id=check.check_id, check_version=check.version,
        is_critical=check.is_critical, weight=check.weight,
    )

    if lead.transcript is None:
        return CheckResult(**base, status="LOW_CONFIDENCE", confidence=0.0,
                            detail="No transcript available to extract from.")

    if check.check_id in _ANCHORS:
        return _score_ground_truth_regex(check, lead, base)
    if check.comparator == "consistency":
        return _score_consistency(check, lead, conn, base)
    # Fallback for any future ground-truth check with no deterministic
    # anchor defined above -- not exercised by current data, kept honest
    # rather than silently NOT_APPLICABLE.
    return _score_ground_truth(check, lead, conn, base)


def _score_ground_truth(check: Check, lead: Lead, conn: sqlite3.Connection, base: dict) -> CheckResult:
    reference = None
    if check.crm_field:
        reference = lead.crm_fields.get(check.crm_field)
    elif check.plan_field:
        reference = lead.plan.get(check.plan_field)

    prompt = _extract_prompt(check.description, lead.transcript)
    extraction = _call_llm(conn, prompt)
    if extraction is None:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=0.0,
            detail="LLM extraction unavailable (no GROQ_API_KEY configured, or the call failed).",
        )

    spoken = extraction.get("spoken_value")
    confidence = float(extraction.get("confidence") or 0.0)
    timing = _timing_fields(lead.transcript, extraction.get("line_number"))

    if spoken is None or confidence < MIN_EXTRACTION_CONFIDENCE:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=confidence,
            transcript_line=extraction.get("transcript_line", ""),
            expected=str(reference) if reference is not None else None, actual=spoken,
            detail="Extraction missing or below confidence threshold -- not a silent pass.",
            **timing,
        )

    match = _values_match(check.comparator, spoken, reference, check.tolerance)
    return CheckResult(
        **base, status=("PASS" if match else "FAIL"), confidence=confidence,
        transcript_line=extraction.get("transcript_line", ""),
        expected=str(reference), actual=str(spoken),
        detail=f"LLM-extracted '{spoken}' vs reference '{reference}'.",
        **timing,
    )


def _extract_pair(conn: sqlite3.Connection, transcript: Transcript, desc_a: str, desc_b: str):
    """Runs two independent single-value extractions and returns
    (ex_a, ex_b) dicts, or (None, None) if either is unavailable."""
    ex_a = _call_llm(conn, _extract_prompt(desc_a, transcript))
    ex_b = _call_llm(conn, _extract_prompt(desc_b, transcript))
    if ex_a is None or ex_b is None:
        return None, None
    return ex_a, ex_b


def _pair_consistent(ex_a: dict, ex_b: dict, tolerance: float) -> tuple[bool | None, float]:
    """Returns (match, confidence). match is None if either value/confidence
    is missing or below threshold -- caller must treat that as LOW_CONFIDENCE,
    not as a mismatch."""
    confidence = min(float(ex_a.get("confidence") or 0.0), float(ex_b.get("confidence") or 0.0))
    val_a, val_b = ex_a.get("spoken_value"), ex_b.get("spoken_value")
    if val_a is None or val_b is None or confidence < MIN_EXTRACTION_CONFIDENCE:
        return None, confidence
    num_a, num_b = _parse_number(val_a), _parse_number(val_b)
    match = num_a is not None and num_b is not None and abs(num_a - num_b) <= tolerance
    return match, confidence


def _score_consistency(check: Check, lead: Lead, conn: sqlite3.Connection, base: dict) -> CheckResult:
    """Checks that one fact (or, if extract_a2/extract_b2 are set, two
    independent facts -- e.g. promo price AND revert price) is stated the
    same way at two different points in the call. Each pair is two
    independent single-value extractions, never a value compared against
    itself, and every value is only ever compared to another extracted
    value -- never to a hardcoded number."""
    params = check.params or {}
    tolerance = check.tolerance or 0.01

    pairs = [(params.get("extract_a", check.description), params.get("extract_b", check.description), "")]
    if params.get("extract_a2"):
        pairs.append((params["extract_a2"], params.get("extract_b2", params["extract_a2"]), " (second fact)"))

    confidences, detail_parts, all_match = [], [], True
    first_val_a = first_val_b = first_ex_a = None

    for desc_a, desc_b, label in pairs:
        ex_a, ex_b = _extract_pair(conn, lead.transcript, desc_a, desc_b)
        if ex_a is None:
            return CheckResult(
                **base, status="LOW_CONFIDENCE", confidence=0.0,
                detail="LLM extraction unavailable (no GROQ_API_KEY configured, or the call failed).",
            )
        match, confidence = _pair_consistent(ex_a, ex_b, tolerance)
        confidences.append(confidence)
        val_a, val_b = ex_a.get("spoken_value"), ex_b.get("spoken_value")
        if first_ex_a is None:
            first_val_a, first_val_b, first_ex_a = val_a, val_b, ex_a

        if match is None:
            detail_parts.append(f"could not confidently extract both mentions{label}")
            all_match = False
        else:
            detail_parts.append(
                f"first{label}: '{val_a}' (turn {ex_a.get('line_number')}); "
                f"second{label}: '{val_b}' (turn {ex_b.get('line_number')}) -> "
                f"{'consistent' if match else 'INCONSISTENT'}"
            )
            all_match = all_match and match

    confidence = min(confidences) if confidences else 0.0
    timing = _timing_fields(lead.transcript, first_ex_a.get("line_number")) if first_ex_a else {}

    if confidence < MIN_EXTRACTION_CONFIDENCE or any("could not confidently" in d for d in detail_parts):
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=confidence,
            expected=first_val_a, actual=first_val_b,
            detail="Not a silent pass -- " + "; ".join(detail_parts) + ".",
            **timing,
        )

    return CheckResult(
        **base, status=("PASS" if all_match else "FAIL"), confidence=confidence,
        expected=str(first_val_a), actual=str(first_val_b),
        detail="; ".join(detail_parts) + ".",
        **timing,
    )
