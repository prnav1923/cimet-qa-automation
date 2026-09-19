"""score_lead(lead, all_checks, conn): resolve checks by call date, run each
check, persist CheckResult rows. Dispatches by check.type. Type B needs a DB
connection (llm_cache).
"""

import argparse
import sqlite3
from datetime import date

from src.adapters.load_checks import load_checks
from src.adapters.load_leads import load_leads
from src.checks.type_a_verbatim import score_type_a
from src.checks.type_b_factual import score_type_b
from src.checks.type_c_behaviour import score_type_c
from src.db import (
    delete_check_results_for_lead,
    get_connection,
    init_db,
    insert_check_result,
    insert_lead,
)
from src.models import Check, CheckResult, Lead

# Two check libraries / lead sources: the synthetic pre-build fixtures, and
# CIMET's real (drafted) checklist against the real transcript. Both are
# loaded everywhere so a lead from either source can be scored and gated.
CHECKS_PATHS = ["data/synthetic/checks_retailer1.json", "data/cimet/checks_cimet.json"]
LEADS_PATHS = ["data/synthetic/leads.json", "data/cimet/leads_cimet.json"]


def load_all_checks() -> list[Check]:
    return [c for path in CHECKS_PATHS for c in load_checks(path)]


def load_all_leads() -> list[Lead]:
    return [l for path in LEADS_PATHS for l in load_leads(path)]


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


def score_check(check: Check, lead: Lead, conn: sqlite3.Connection) -> CheckResult:
    if check.type == "A":
        return score_type_a(check, lead)
    if check.type == "B":
        return score_type_b(check, lead, conn)
    if check.type == "C":
        return score_type_c(check, lead)
    raise ValueError(f"{check.check_id}: unknown check type {check.type!r}")


def score_lead(lead: Lead, all_checks: list[Check], conn: sqlite3.Connection) -> list[CheckResult]:
    checks = resolve_checks(all_checks, lead.retailer_id, lead.call_date)
    return [score_check(check, lead, conn) for check in checks]


def _format_ts(r: CheckResult) -> str:
    if r.start_ts is not None:
        return f"{r.start_ts:.1f}"
    if r.estimated_ts is not None:
        line = f" L{r.line_number}" if r.line_number is not None else ""
        return f"~{r.estimated_ts:.1f}{line}"
    return "-"


def _print_report(lead: Lead, results: list[CheckResult]) -> None:
    print(f"Scored {lead.lead_id} ({lead.retailer_id}, call_date={lead.call_date}): {len(results)} checks")
    for r in results:
        crit = "critical" if r.is_critical else "non-critical"
        print(
            f"  [{r.check_id} v{r.check_version}] {r.status:14s} ts={_format_ts(r):>10s} "
            f"conf={r.confidence:.2f} ({crit})  {r.detail}"
        )
        if r.expected is not None or r.actual is not None:
            print(f"      expected={r.expected!r} actual={r.actual!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead", required=True)
    args = parser.parse_args()

    all_checks = load_all_checks()
    leads = load_all_leads()
    lead = next((l for l in leads if l.lead_id == args.lead), None)
    if lead is None:
        raise SystemExit(f"lead {args.lead} not found in {LEADS_PATHS}")

    init_db()
    conn = get_connection()
    try:
        results = score_lead(lead, all_checks, conn)
        insert_lead(conn, lead)  # check_results.lead_id has a foreign key to leads
        delete_check_results_for_lead(conn, lead.lead_id)  # re-runs don't accumulate stale rows
        for r in results:
            insert_check_result(conn, r)
    finally:
        conn.close()

    _print_report(lead, results)


if __name__ == "__main__":
    main()
