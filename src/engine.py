"""score_lead(lead, all_checks): resolve checks by call date, run each check,
persist CheckResult rows. Dispatches by check.type; Type B is a placeholder
until P5.
"""

import argparse
from datetime import date

from src.adapters.load_checks import load_checks
from src.adapters.load_leads import load_leads
from src.checks.type_a_verbatim import score_type_a
from src.checks.type_c_behaviour import score_type_c
from src.db import get_connection, init_db, insert_check_result, insert_lead
from src.models import Check, CheckResult, Lead

CHECKS_PATH = "data/synthetic/checks_retailer1.json"
LEADS_PATH = "data/synthetic/leads.json"


def resolve_checks(all_checks: list[Check], retailer_id: str, call_date: date) -> list[Check]:
    """Checks in force on the call date. Never 'today's version'."""
    resolved = []
    for check in all_checks:
        if check.retailer_id != retailer_id:
            continue
        if check.effective_from > call_date:
            continue
        if check.effective_to is not None and call_date >= check.effective_to:
            continue
        resolved.append(check)
    return resolved


def _score_type_b_placeholder(check: Check, lead: Lead) -> CheckResult:
    return CheckResult(
        lead_id=lead.lead_id, check_id=check.check_id, check_version=check.version,
        status="LOW_CONFIDENCE", confidence=0.0,
        is_critical=check.is_critical, weight=check.weight,
        detail="Type B factual extraction not implemented until P5.",
    )


def score_check(check: Check, lead: Lead) -> CheckResult:
    if check.type == "A":
        return score_type_a(check, lead)
    if check.type == "B":
        return _score_type_b_placeholder(check, lead)
    if check.type == "C":
        return score_type_c(check, lead)
    raise ValueError(f"{check.check_id}: unknown check type {check.type!r}")


def score_lead(lead: Lead, all_checks: list[Check]) -> list[CheckResult]:
    checks = resolve_checks(all_checks, lead.retailer_id, lead.call_date)
    return [score_check(check, lead) for check in checks]


def _print_report(lead: Lead, results: list[CheckResult]) -> None:
    print(f"Scored {lead.lead_id} ({lead.retailer_id}, call_date={lead.call_date}): {len(results)} checks")
    for r in results:
        ts = f"{r.start_ts:.1f}" if r.start_ts is not None else "-"
        crit = "critical" if r.is_critical else "non-critical"
        print(
            f"  [{r.check_id} v{r.check_version}] {r.status:14s} ts={ts:>7s} "
            f"conf={r.confidence:.2f} ({crit})  {r.detail}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead", required=True)
    args = parser.parse_args()

    all_checks = load_checks(CHECKS_PATH)
    leads = load_leads(LEADS_PATH)
    lead = next((l for l in leads if l.lead_id == args.lead), None)
    if lead is None:
        raise SystemExit(f"lead {args.lead} not found in {LEADS_PATH}")

    results = score_lead(lead, all_checks)

    init_db()
    conn = get_connection()
    try:
        insert_lead(conn, lead)  # check_results.lead_id has a foreign key to leads
        for r in results:
            insert_check_result(conn, r)
    finally:
        conn.close()

    _print_report(lead, results)


if __name__ == "__main__":
    main()
