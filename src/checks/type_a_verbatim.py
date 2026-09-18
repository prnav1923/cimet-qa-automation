"""Type A — verbatim script checks.

Slides a window over the transcript's flattened word list by scoring the
whole transcript against the check's expected_script_text with
rapidfuzz.fuzz.partial_ratio_alignment, which internally finds the
best-matching substring and its exact character bounds. Those bounds are
mapped back to word indices to give a tight matched span -- not just
whichever fixed-size window happened to score best, which can otherwise
"smuggle in" a few words from an adjacent sentence and pull in a stray
low-confidence word that was never really part of the match.
"""

from rapidfuzz import fuzz

from src.models import Check, CheckResult, Lead


def _char_offsets(words: list) -> tuple[str, list[tuple[int, int]]]:
    """Joins word display text with single spaces; returns the joined text
    plus each word's (char_start, char_end) offset within it."""
    parts = []
    offsets = []
    pos = 0
    for w in words:
        text = w.punctuated or w.text
        offsets.append((pos, pos + len(text)))
        parts.append(text)
        pos += len(text) + 1  # +1 for the joining space
    return " ".join(parts), offsets


def _word_range_for_chars(offsets: list[tuple[int, int]], char_start: int, char_end: int) -> tuple[int, int]:
    """Maps a [char_start, char_end) span back to a [word_start, word_end) index range."""
    start_idx = 0
    for i, (_, o_end) in enumerate(offsets):
        if o_end > char_start:
            start_idx = i
            break
    end_idx = start_idx + 1
    for i in range(len(offsets) - 1, -1, -1):
        o_start, _ = offsets[i]
        if o_start < char_end:
            end_idx = i + 1
            break
    return start_idx, end_idx


def _best_span(expected: str, words: list) -> tuple[float, int, int]:
    """Returns (similarity 0-1, start_idx, end_idx) of the best-matching
    word span against expected. end_idx is exclusive."""
    full_text, offsets = _char_offsets(words)
    alignment = fuzz.partial_ratio_alignment(expected.lower(), full_text.lower())
    start_idx, end_idx = _word_range_for_chars(offsets, alignment.dest_start, alignment.dest_end)
    return alignment.score / 100.0, start_idx, end_idx


def score_type_a(check: Check, lead: Lead) -> CheckResult:
    base = dict(
        lead_id=lead.lead_id, check_id=check.check_id, check_version=check.version,
        is_critical=check.is_critical, weight=check.weight,
        expected=check.expected_script_text,
    )

    transcript = lead.transcript
    words = transcript.words if transcript else []
    expected = check.expected_script_text or ""

    if not words or not expected:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=0.0,
            detail="No transcript words available to match against.",
        )

    similarity, start_idx, end_idx = _best_span(expected, words)
    span_words = words[start_idx:end_idx]
    span_text = " ".join(w.punctuated or w.text for w in span_words)
    span_min_conf = min(w.confidence for w in span_words)
    start_ts = span_words[0].start
    end_ts = span_words[-1].end

    if similarity >= check.pass_at:
        if span_min_conf < check.min_word_confidence:
            low_conf_word = min(span_words, key=lambda w: w.confidence)
            return CheckResult(
                **base, status="LOW_CONFIDENCE", confidence=similarity,
                transcript_line=span_text, start_ts=start_ts, end_ts=end_ts,
                actual=span_text, asr_confidence=span_min_conf,
                detail=(
                    f"Matched with {similarity:.0%} similarity, but downgraded: "
                    f"word '{low_conf_word.text}' had ASR confidence "
                    f"{low_conf_word.confidence:.2f} < min_word_confidence "
                    f"{check.min_word_confidence:.2f}."
                ),
            )
        return CheckResult(
            **base, status="PASS", confidence=similarity,
            transcript_line=span_text, start_ts=start_ts, end_ts=end_ts,
            actual=span_text, asr_confidence=span_min_conf,
            detail=f"Matched with {similarity:.0%} similarity.",
        )

    if similarity <= check.fail_at:
        return CheckResult(
            **base, status="FAIL", confidence=similarity,
            transcript_line=span_text, start_ts=start_ts, end_ts=end_ts,
            actual=span_text, asr_confidence=span_min_conf,
            detail=(
                f"Best match similarity only {similarity:.0%}, at or below "
                f"fail_at ({check.fail_at:.0%})."
            ),
        )

    return CheckResult(
        **base, status="LOW_CONFIDENCE", confidence=similarity,
        transcript_line=span_text, start_ts=start_ts, end_ts=end_ts,
        actual=span_text, asr_confidence=span_min_conf,
        detail=(
            f"Similarity {similarity:.0%} is between fail_at "
            f"({check.fail_at:.0%}) and pass_at ({check.pass_at:.0%})."
        ),
    )
