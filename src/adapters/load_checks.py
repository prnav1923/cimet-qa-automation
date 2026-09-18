"""Parses a retailer's check-library export (CIMET format, or the synthetic
stand-in built to mimic it) into a list of Check objects.

The only place that knows the shape of the check-library export. Nothing
outside src/adapters/ may parse this format directly.
"""

from src.models import Check


def load_checks(path: str) -> list[Check]:
    raise NotImplementedError(
        "load_checks: parse a check-library export (retailer_id, checks[]) "
        "into Check objects. Implemented in P1 against the synthetic format."
    )
