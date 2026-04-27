"""
Walego: LinkedIn execution only. Our system hands off lead payloads and receives
engagement signals (no LinkedIn copy authored here—avoid duplicate messaging).
"""
from __future__ import annotations

import json
import hashlib
import pandas as pd


def build_walego_payload(lead: pd.Series, target_role: str | None = None) -> dict:
    role = target_role or str(lead.get("Title", "Sales role"))
    return {
        "name": str(lead.get("Name", "")),
        "linkedin_url": str(lead.get("LinkedIn", "")),
        "company": str(lead.get("Company", "")),
        "target_role": role,
    }


def handoff_to_walego(lead: pd.Series) -> str:
    """V1: return JSON string for log/API; in prod POST to Walego."""
    p = build_walego_payload(lead)
    return json.dumps(p, ensure_ascii=True)


# Deterministic mock engagement from a stable key (no real Walego call)
def mock_walego_engagement(lead: pd.Series) -> dict:
    h = int(hashlib.md5(str(lead.get("Email", lead.get("Name", "x"))).encode()).hexdigest()[:8], 16)
    return {
        "connection_request_sent": True,
        "accepted": (h % 3) != 0,
        "messages_in_sequence": 2,
        "replies": 1 if (h % 5) == 0 else 0,
        "profile_views": 1 + (h % 2),
    }
