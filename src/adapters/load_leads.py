"""Parses CIMET's lead dataset export (or the synthetic stand-in) into a list
of Lead objects, attaching each lead's Transcript via load_transcript.

The only place that knows the shape of the lead dataset export. Nothing
outside src/adapters/ may parse this format directly.
"""

from src.models import Lead


def load_leads(path: str) -> list[Lead]:
    raise NotImplementedError(
        "load_leads: parse a lead dataset export (lead_id, retailer_id, "
        "call_date, crm_fields, plan, recording_path, ...) into Lead objects. "
        "Implemented in P1 against the synthetic format."
    )
