"""
CRM downstream: only qualified (Interested) leads. Full handoff for sales.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import pandas as pd

def _id_for(lead: pd.Series) -> str:
    raw = f"{lead.get('Email', '')}{lead.get('Name', '')}{lead.get('Company', '')}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def build_crm_record(
    lead: pd.Series,
    interaction_log: str,
    status: str = "Interested",
) -> dict:
    if status not in ("Interested", "Booked", "Closed"):
        status = "Interested"
    return {
        "id": _id_for(lead),
        "name": str(lead.get("Name", "")),
        "company": str(lead.get("Company", "")),
        "email": str(lead.get("Email", "")),
        "linkedin": str(lead.get("LinkedIn", "")),
        "phone": str(lead.get("Phone", "")),
        "intent_reason": str(lead.get("Intent reason", "")),
        "interaction_history": interaction_log,
        "status": status,
        "pushed_at": datetime.utcnow().isoformat() + "Z",
    }


def to_crm_dataframe(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=[
                "id",
                "name",
                "company",
                "email",
                "linkedin",
                "phone",
                "intent_reason",
                "interaction_history",
                "status",
                "pushed_at",
            ]
        )
    return pd.DataFrame(records)
