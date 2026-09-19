"""Type C — behaviour checks: dead air, interruptions, talk ratio.

All three read turn timings off Transcript.sorted_turns(), which is always
sorted by start -- word-level timing anomalies never affect these, only
genuine turn-level gaps and overlaps do.

When transcript.has_word_timings is False (a no-audio, estimated-timing
source -- see load_transcript.py), dead air is NOT_APPLICABLE outright (it
fundamentally requires measured silence), and talk ratio / interruptions
fall back to text-based methods, each labelling which method it used.
"""

import re

from src.models import Check, CheckResult, Lead, Transcript

# Short acknowledgement tokens that, appearing as their own short sentence
# mid-turn (not the turn's opening clause) AND immediately after a sentence
# ending in "?", are evidence the transcription merged in a reply to that
# question from the other speaker with no turn break. "k"/"kay" are excluded
# -- on the real CIMET call this speaker uses "K?" as a personal verbal tic,
# which isn't an embedded reply and inflated the count when included.
_ACK_WORDS = {
    "yeah", "yep", "yes", "no", "okay", "ok",
    "correct", "right", "mhmm", "sure",
}
_SENTENCE_SPLIT_RE = re.compile(r"([.?!]+)")  # capturing group keeps the delimiter


def score_type_c(check: Check, lead: Lead) -> CheckResult:
    base = dict(
        lead_id=lead.lead_id, check_id=check.check_id, check_version=check.version,
        is_critical=check.is_critical, weight=check.weight,
    )

    transcript = lead.transcript
    if transcript is None or not transcript.turns:
        return CheckResult(
            **base, status="LOW_CONFIDENCE", confidence=0.0,
            detail="No transcript turns available to compute behaviour from.",
        )

    if "max_dead_air_s" in check.params:
        return _dead_air(check, base, transcript)
    if "max_interruptions" in check.params:
        return _interruptions(check, base, transcript)
    if "max_agent_talk_ratio" in check.params:
        return _talk_ratio(check, base, transcript)
    if check.params.get("guardrail") == "mute_before_payment":
        return _mute_before_payment(check, base, transcript)
    raise ValueError(f"{check.check_id}: unrecognised Type C params {check.params}")


def _mute_before_payment(check: Check, base: dict, transcript: Transcript) -> CheckResult:
    """No-card-data-by-voice boundary: the agent must mute the recording
    before collecting payment details and resume it after -- confirmed by
    finding both phrases and checking their order, by word position (they
    can land in the same turn, since speaker separation isn't reliable)."""
    words = transcript.words
    mute_word = next((w for w in words if "mute" in w.text), None)
    resume_word = next((w for w in words if w.text.startswith("resum")), None)

    def _timing(word):
        if transcript.has_word_timings:
            return {"start_ts": word.start, "end_ts": word.end}
        return {"line_number": word.line_number, "estimated_ts": word.start, "estimated_end_ts": word.end}

    if mute_word is None or resume_word is None:
        missing = "mute" if mute_word is None else "resume"
        return CheckResult(
            **base, status="FAIL", confidence=1.0,
            detail=f"No mention of the recording being {missing}d found -- cannot confirm the guardrail held.",
        )

    ordered = mute_word.start <= resume_word.start
    status = "PASS" if ordered else "FAIL"
    detail = (
        f"Recording muted (\"{mute_word.punctuated}\") "
        f"{'before' if ordered else 'AFTER'} it was resumed (\"{resume_word.punctuated}\")."
    )
    return CheckResult(**base, status=status, confidence=1.0, detail=detail, **_timing(mute_word))


def _dead_air(check: Check, base: dict, transcript: Transcript) -> CheckResult:
    if not transcript.has_word_timings:
        return CheckResult(
            **base, status="NOT_APPLICABLE", confidence=0.0,
            detail=(
                "Not evaluable with supplied data: dead air requires measured "
                "audio timing, but this transcript's timestamps are estimated "
                "from word position."
            ),
        )

    max_dead_air_s = check.params["max_dead_air_s"]
    turns = transcript.sorted_turns()

    longest_gap = 0.0
    gap_start_ts = None
    gap_end_ts = None
    for cur, nxt in zip(turns, turns[1:]):
        gap = max(0.0, nxt.start - cur.end)
        if gap > longest_gap:
            longest_gap = gap
            gap_start_ts = cur.end
            gap_end_ts = nxt.start

    status = "FAIL" if longest_gap > max_dead_air_s else "PASS"
    detail = f"Longest silence was {longest_gap:.1f}s (limit {max_dead_air_s}s)."
    return CheckResult(
        **base, status=status, confidence=1.0,
        start_ts=gap_start_ts, end_ts=gap_end_ts,
        expected=f"<= {max_dead_air_s}s", actual=f"{longest_gap:.1f}s",
        detail=detail,
    )


def _interruptions(check: Check, base: dict, transcript: Transcript) -> CheckResult:
    max_interruptions = check.params["max_interruptions"]
    turns = transcript.sorted_turns()

    if not transcript.has_word_timings:
        return _interruptions_run_together(max_interruptions, base, turns)

    count = 0
    first_ts = None
    for cur, nxt in zip(turns, turns[1:]):
        if nxt.start < cur.end:  # negative gap = overlap = interruption
            count += 1
            if first_ts is None:
                first_ts = nxt.start

    status = "FAIL" if count > max_interruptions else "PASS"
    return CheckResult(
        **base, status=status, confidence=1.0,
        start_ts=first_ts,
        expected=f"<= {max_interruptions}", actual=str(count),
        detail=(
            f"method: turn-overlap timing. {count} overlapping turn(s) "
            f"(limit {max_interruptions})."
        ),
    )


def _interruptions_run_together(max_interruptions: int, base: dict, turns: list) -> CheckResult:
    """No audio timing -> can't detect overlaps. Instead flags a short
    acknowledgement sentence appearing mid-turn (not the turn's opener),
    immediately after a sentence ending in "?", as evidence the
    transcription ran a reply to that question in with no turn break -- see
    module docstring."""
    count = 0
    first_line_number = None
    first_ts = None
    for turn in turns:
        parts = _SENTENCE_SPLIT_RE.split(turn.text)
        chunks = [parts[i].strip() for i in range(0, len(parts), 2)]
        delims = [parts[i] for i in range(1, len(parts), 2)]
        for i in range(1, len(chunks)):
            if not chunks[i] or i - 1 >= len(delims) or "?" not in delims[i - 1]:
                continue
            tokens = chunks[i].split()
            if len(tokens) <= 2 and tokens[0].lower() in _ACK_WORDS:
                count += 1
                if first_line_number is None:
                    first_line_number = turn.line_number
                    first_ts = turn.start

    status = "FAIL" if count > max_interruptions else "PASS"
    return CheckResult(
        **base, status=status, confidence=1.0,
        line_number=first_line_number, estimated_ts=first_ts,
        expected=f"<= {max_interruptions}", actual=str(count),
        detail=(
            f"method: run-together speech detection (no audio timing available). "
            f"{count} embedded short-reply event(s) found mid-turn, each "
            f"immediately after a '?' (limit {max_interruptions})."
        ),
    )


def _talk_ratio(check: Check, base: dict, transcript: Transcript) -> CheckResult:
    max_ratio = check.params["max_agent_talk_ratio"]
    turns = transcript.sorted_turns()

    if transcript.has_word_timings:
        agent_amount = sum(max(0.0, t.end - t.start) for t in turns if t.speaker == "AGENT")
        total_amount = sum(max(0.0, t.end - t.start) for t in turns)
        method = "duration"
    else:
        agent_amount = sum(len(t.words) for t in turns if t.speaker == "AGENT")
        total_amount = sum(len(t.words) for t in turns)
        method = "word count (no audio duration available)"

    ratio = agent_amount / total_amount if total_amount > 0 else 0.0

    status = "FAIL" if ratio > max_ratio else "PASS"
    detail = f"method: {method}. Agent talk ratio {ratio:.0%} (limit {max_ratio:.0%})."
    if not transcript.has_word_timings:
        detail += (
            " Caveat: speaker separation is unreliable in this source -- a "
            "turn's word count may include some of the other party's words "
            "run together with no break, so this can over-attribute to whoever "
            "is labelled for that turn."
        )
    return CheckResult(
        **base, status=status, confidence=1.0,
        expected=f"<= {max_ratio:.0%}", actual=f"{ratio:.0%}",
        detail=detail,
    )
