"""Social intent: in-house implementation (delegates to internal_intent)."""

from __future__ import annotations

from internal_intent import fetch_social_intent


def get_apify_social_health() -> dict[str, str]:
    """Legacy helper kept for compatibility; Apify is not used in the in-house build."""
    return {"status": "ok", "message": "Using verified live job-board feed (no Apify)."}
