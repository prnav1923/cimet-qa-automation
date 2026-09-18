"""Type C — behaviour checks: dead air, interruptions, talk ratio.

All three read turn timings off Transcript.sorted_turns(), which is always
sorted by start -- word-level timing anomalies never affect these, only
genuine turn-level gaps and overlaps do.
"""

from src.models import Check, CheckResult, Lead, Transcript


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
    raise ValueError(f"{check.check_id}: unrecognised Type C params {check.params}")


def _dead_air(check: Check, base: dict, transcript: Transcript) -> CheckResult:
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
        detail=f"{count} overlapping turn(s) (limit {max_interruptions}).",
    )


def _talk_ratio(check: Check, base: dict, transcript: Transcript) -> CheckResult:
    max_ratio = check.params["max_agent_talk_ratio"]
    turns = transcript.sorted_turns()

    agent_seconds = sum(max(0.0, t.end - t.start) for t in turns if t.speaker == "AGENT")
    total_seconds = sum(max(0.0, t.end - t.start) for t in turns)
    ratio = agent_seconds / total_seconds if total_seconds > 0 else 0.0

    status = "FAIL" if ratio > max_ratio else "PASS"
    return CheckResult(
        **base, status=status, confidence=1.0,
        expected=f"<= {max_ratio:.0%}", actual=f"{ratio:.0%}",
        detail=f"Agent talk ratio {ratio:.0%} (limit {max_ratio:.0%}).",
    )
