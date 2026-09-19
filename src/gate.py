"""Gate precedence, deterministic sampling, scoring, overrides, and the
card-number guardrail. python -m src.gate --all runs every synthetic lead
through the engine and the gate, persists results, and reports against
expected_outcomes.json.
"""

import argparse
import hashlib
import json
import re
from dataclasses import replace

from src.db import (
    delete_check_results_for_lead,
    get_check_results_for_lead,
    get_connection,
    init_db,
    insert_check_result,
    insert_decision,
    insert_lead,
    insert_override,
)
from src.engine import load_all_checks, load_all_leads, resolve_checks, score_check
from src.models import CheckResult, Decision, Lead, Override

EXPECTED_OUTCOMES_PATH = "data/synthetic/expected_outcomes.json"

# 13-19 digits, optionally grouped with spaces/dashes -- matches both a
# solid card-number run and the grouped-token form ASR/transcripts produce
# (e.g. "4111 1111 1111 1111").
CARD_NUMBER_RE = re.compile(r"(?:\d[ -]?){13,19}")


def is_sampled(lead_id: str, rate_pct: int = 5) -> bool:
    """Deterministic sample. Never random -- the demo must reproduce."""
    h = hashlib.md5(lead_id.encode()).hexdigest()
    return int(h, 16) % 100 < rate_pct


def mask_card_numbers(text: str) -> str:
    """Card data is never displayed, in any view -- the number itself, not
    just its presence, is redacted."""
    return CARD_NUMBER_RE.sub("[CARD REDACTED]", text)


def has_card_number(lead: Lead) -> bool:
    if lead.transcript is None:
        return False
    return bool(CARD_NUMBER_RE.search(lead.transcript.full_text))


def score_without_fatals(results: list[CheckResult]) -> float:
    """Weighted % of non-critical checks passed. NOT_APPLICABLE checks are
    excluded entirely -- they neither help nor hurt the score."""
    scored = [r for r in results if not r.is_critical and r.status != "NOT_APPLICABLE"]
    total_weight = sum(r.weight for r in scored)
    if total_weight == 0:
        return 1.0  # nothing to penalise
    passed_weight = sum(r.weight for r in scored if r.status == "PASS")
    return passed_weight / total_weight


def gate(results: list[CheckResult], lead: Lead) -> Decision:
    """Exact precedence from CLAUDE.md, with the amended NOT_APPLICABLE rule:
    critical FAIL or critical NOT_APPLICABLE  -> HELD
    elif any LOW_CONFIDENCE                   -> QA_REVIEW
    elif sampled                              -> AUTO_SUBMIT + QA sample copy
    else                                      -> AUTO_SUBMIT
    Non-critical NOT_APPLICABLE results never enter this precedence chain.
    A card-number violation forces HELD regardless of check results.
    """
    sampled = is_sampled(lead.lead_id)
    without_fatals = score_without_fatals(results)

    critical_fatal = [r for r in results if r.is_critical and r.status in ("FAIL", "NOT_APPLICABLE")]
    card_violation = has_card_number(lead)
    with_fatals = 0.0 if (critical_fatal or card_violation) else without_fatals

    if critical_fatal or card_violation:
        reasons = [f"{r.check_id}={r.status}" for r in critical_fatal]
        if card_violation:
            reasons.append("card number detected in transcript (guardrail)")
        return Decision(
            lead_id=lead.lead_id, gate_status="HELD", reason="; ".join(reasons),
            sampled=sampled, score_with_fatals=with_fatals, score_without_fatals=without_fatals,
        )

    low_confidence = [r for r in results if r.status == "LOW_CONFIDENCE"]
    if low_confidence:
        reasons = "; ".join(f"{r.check_id}=LOW_CONFIDENCE" for r in low_confidence)
        return Decision(
            lead_id=lead.lead_id, gate_status="QA_REVIEW", reason=reasons,
            sampled=sampled, score_with_fatals=with_fatals, score_without_fatals=without_fatals,
        )

    reason = "all checks passed" + (" (sampled for QA)" if sampled else "")
    return Decision(
        lead_id=lead.lead_id, gate_status="AUTO_SUBMIT", reason=reason,
        sampled=sampled, score_with_fatals=with_fatals, score_without_fatals=without_fatals,
    )


def apply_override(conn, lead_id: str, check_id: str, actor: str, new_status: str, reason: str) -> Override:
    """Logs a human override. actor and reason are mandatory -- this never
    silently rewrites a result."""
    if not actor or not actor.strip():
        raise ValueError("override requires a non-empty actor")
    if not reason or not reason.strip():
        raise ValueError("override requires a non-empty reason")
    if new_status not in ("PASS", "FAIL", "LOW_CONFIDENCE", "NOT_APPLICABLE"):
        raise ValueError(f"invalid status {new_status!r}")

    rows = [r for r in get_check_results_for_lead(conn, lead_id) if r["check_id"] == check_id]
    if not rows:
        raise ValueError(f"no check_result found for {lead_id}/{check_id}")
    old_status = rows[-1]["status"]  # most recently scored

    override = Override(
        lead_id=lead_id, check_id=check_id, actor=actor,
        old_status=old_status, new_status=new_status, reason=reason,
    )
    insert_override(conn, override)
    return override


def _blocked_only_by_type_b_extraction(results: list[CheckResult], lead: Lead, expected_gate: str) -> bool:
    """True if this lead's actual gate outcome disagrees with the expected
    one, but would agree if every Type B check that couldn't extract (no
    GROQ_API_KEY, or a genuinely low-confidence extraction) had PASSed
    instead -- i.e. the only thing standing between this lead and its
    intended outcome is a missing/uncertain LLM extraction, not a real
    defect elsewhere in the scoring."""
    hypothetical = [
        replace(r, status="PASS")
        if (r.check_id.startswith("CHK_B_") and r.status in ("NOT_APPLICABLE", "LOW_CONFIDENCE"))
        else r
        for r in results
    ]
    return gate(hypothetical, lead).gate_status == expected_gate


def run_all() -> None:
    all_checks = load_all_checks()
    leads = load_all_leads()
    with open(EXPECTED_OUTCOMES_PATH) as f:
        expected_by_lead = {row["lead_id"]: row for row in json.load(f)}

    init_db()
    conn = get_connection()

    report_rows = []
    try:
        for lead in leads:
            checks = resolve_checks(all_checks, lead.retailer_id, lead.call_date)
            results = [score_check(c, lead, conn) for c in checks]

            insert_lead(conn, lead)
            delete_check_results_for_lead(conn, lead.lead_id)
            for r in results:
                insert_check_result(conn, r)

            decision = gate(results, lead)
            insert_decision(conn, decision)

            expected = expected_by_lead.get(lead.lead_id)
            if expected is None:
                # No oracle for this lead (e.g. CIMET's real call has no
                # hand-authored expected_outcomes.json entry) -- report it,
                # don't force a false match/mismatch verdict.
                report_rows.append((lead.lead_id, None, decision.gate_status, None,
                                     decision.sampled, None, "no expected outcome on file"))
                continue

            expected_gate = expected.get("gate_status")
            expected_sampled = expected.get("sampled")
            match = decision.gate_status == expected_gate

            note = ""
            if not match:
                if _blocked_only_by_type_b_extraction(results, lead, expected_gate):
                    note = "blocked only by Type B extraction (needs GROQ_API_KEY)"
                else:
                    note = "MISMATCH"

            report_rows.append((
                lead.lead_id, expected_gate, decision.gate_status, match,
                decision.sampled, expected_sampled, note,
            ))
    finally:
        conn.close()

    _print_report(report_rows)


def _print_report(rows: list[tuple]) -> None:
    print(f"{'lead_id':<16} {'expected':<12} {'actual':<12} {'match':<6} {'sampled':<8} {'note'}")
    n_match = 0
    n_placeholder_blocked = 0
    n_with_oracle = 0
    for lead_id, expected_gate, actual_gate, match, sampled, expected_sampled, note in rows:
        sampled_str = str(sampled)
        if expected_sampled is not None and sampled != expected_sampled:
            sampled_str += f" (expected {expected_sampled})"
        print(f"{lead_id:<16} {expected_gate or '-':<12} {actual_gate:<12} {str(match):<6} {sampled_str:<8} {note}")
        if match is not None:
            n_with_oracle += 1
            n_match += match
        n_placeholder_blocked += note == "blocked only by Type B extraction (needs GROQ_API_KEY)"

    print(f"\n{n_match}/{n_with_oracle} leads with an oracle match expected_outcomes.json "
          f"({len(rows) - n_with_oracle} leads have no expected_outcomes.json entry)")
    print(f"{n_placeholder_blocked}/{n_with_oracle} leads blocked only by the Type B placeholder")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", required=True)
    parser.parse_args()
    run_all()


if __name__ == "__main__":
    main()
