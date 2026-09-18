"""Maps internal results (CheckResult rows + a Decision) for one lead into the
CIMET scoring-sandbox payload shape (see payload_shape.json / SYNTHETIC-DATA.md).

The only place that knows the sandbox payload format. Nothing outside
src/adapters/ may construct it directly.
"""

from typing import Any

from src.models import CheckResult, Decision, Lead


def map_to_payload(
    lead: Lead, results: list[CheckResult], decision: Decision
) -> dict[str, Any]:
    raise NotImplementedError(
        "map_to_payload: convert a Lead's CheckResults and Decision into the "
        "CIMET sandbox payload shape. Implemented in P7 against the synthetic "
        "payload_shape.json contract."
    )
