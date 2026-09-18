"""Parses CIMET's lead dataset export (or the synthetic stand-in) into a list
of Lead objects, attaching each lead's Transcript via load_transcript.

P1 implements only the synthetic format: a JSON list of lead rows (see
SYNTHETIC-DATA.md section 3), with each lead's transcript at
transcripts/<lead_id>.json and its plan resolved from a sibling
rate_card.json via plan_id.

The only place that knows the shape of the lead dataset export. Nothing
outside src/adapters/ may parse this format directly.
"""

import json
from datetime import date
from pathlib import Path

from src.adapters.load_transcript import load_transcript
from src.models import Lead


def load_leads(path: str) -> list[Lead]:
    base = Path(path).parent
    with open(path) as f:
        rows = json.load(f)

    rate_card_path = base / "rate_card.json"
    plans_by_id = {}
    if rate_card_path.exists():
        with open(rate_card_path) as f:
            plans_by_id = {p["plan_id"]: p for p in json.load(f)}

    leads = []
    for row in rows:
        lead_id = row["lead_id"]
        transcript_path = base / "transcripts" / f"{lead_id}.json"
        transcript = load_transcript(str(transcript_path)) if transcript_path.exists() else None

        provenance = {}
        plan = plans_by_id.get(row.get("plan_id"))
        if plan is None and row.get("plan_id"):
            plan = {}
            provenance["plan"] = f"plan_id {row['plan_id']} not found in rate_card.json"

        leads.append(Lead(
            lead_id=lead_id,
            retailer_id=row["retailer_id"],
            call_date=date.fromisoformat(row["call_date"]),
            agent_id=row.get("agent_id", "UNKNOWN"),
            campaign=row.get("campaign", "UNKNOWN"),
            team_lead_id=row.get("team_lead_id", "UNKNOWN"),
            recording_path=row.get("recording_path"),
            transcript=transcript,
            crm_fields=row.get("crm_fields", {}),
            plan=plan or {},
            raw=row,
            provenance=provenance,
        ))
    return leads
