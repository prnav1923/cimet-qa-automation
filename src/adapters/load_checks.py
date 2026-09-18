"""Parses a retailer's check-library export (CIMET format, or the synthetic
stand-in built to mimic it) into a list of Check objects.

The only place that knows the shape of the check-library export. Nothing
outside src/adapters/ may parse this format directly.
"""

import json
from datetime import date

from src.models import Check


def _parse_date(value):
    return date.fromisoformat(value) if value else date(1970, 1, 1)


def _parse_optional_date(value):
    return date.fromisoformat(value) if value else None


def load_checks(path: str) -> list[Check]:
    with open(path) as f:
        data = json.load(f)

    retailer_id = data["retailer_id"]
    checks = []
    for row in data.get("checks", []):
        checks.append(Check(
            check_id=row["check_id"],
            retailer_id=retailer_id,
            type=row["type"],
            description=row["description"],
            is_critical=bool(row.get("is_critical", False)),
            weight=row.get("weight", 1.0),
            version=row.get("version", 1),
            effective_from=_parse_date(row.get("effective_from")),
            effective_to=_parse_optional_date(row.get("effective_to")),
            expected_script_text=row.get("expected_script_text"),
            pass_at=row.get("pass_at", 0.85),
            fail_at=row.get("fail_at", 0.60),
            min_word_confidence=row.get("min_word_confidence", 0.55),
            crm_field=row.get("crm_field"),
            plan_field=row.get("plan_field"),
            comparator=row.get("comparator"),
            tolerance=row.get("tolerance", 0.0),
            params=row.get("params", {}),
            raw=row,
            provenance=row.get("provenance", {}),
        ))
    return checks
