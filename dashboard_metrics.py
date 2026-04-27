"""
Client-facing metrics: funnel, intent quality, engagement, conversion, pipeline health.
V1: accepts counters + dataframes; safe defaults when empty.
"""
from __future__ import annotations

import pandas as pd


def build_dashboard(
    n_leads_generated: int,
    emails_sent: int,
    walego_actions: int,
    company_scored: pd.DataFrame | None,
    replies_total: int,
    positive_replies: int,
    unsubscribes: int,
    walego_accepted: int,
    walego_requests: int,
    interested_in_crm: int,
    booked_calls: int,
    active_conversations: int,
    stalled_leads: int,
) -> dict:
    def tier_count(df: pd.DataFrame | None, tier: str) -> int:
        if df is None or df.empty or "Intent tier" not in df.columns:
            return 0
        return int((df["Intent tier"] == tier).sum())

    high = tier_count(company_scored, "High")
    med = tier_count(company_scored, "Medium")
    low = tier_count(company_scored, "Low")
    avg_score = float(company_scored["Intent score"].mean()) if company_scored is not None and not company_scored.empty and "Intent score" in company_scored.columns else 0.0

    reply_rate = (replies_total / emails_sent * 100.0) if emails_sent else 0.0
    pos_rate = (positive_replies / replies_total * 100.0) if replies_total else 0.0
    li_rate = (walego_accepted / walego_requests * 100.0) if walego_requests else 0.0
    conv = (booked_calls / n_leads_generated * 100.0) if n_leads_generated else 0.0

    return {
        "top": {
            "leads_generated": n_leads_generated,
            "emails_sent": emails_sent,
            "linkedin_actions": walego_actions,
        },
        "intent": {
            "high": high,
            "medium": med,
            "low": low,
            "avg_intent_score": round(avg_score, 1),
        },
        "engagement": {
            "replies": replies_total,
            "reply_rate_pct": round(reply_rate, 1),
            "positive_reply_rate_pct": round(pos_rate, 1),
            "unsubscribes": unsubscribes,
            "linkedin_acceptance_rate_pct": round(li_rate, 1),
        },
        "conversions": {
            "interested_in_crm": interested_in_crm,
            "booked_calls": booked_calls,
            "lead_to_call_rate_pct": round(conv, 1),
        },
        "health": {
            "active_conversations": active_conversations,
            "stalled_leads": stalled_leads,
        },
    }
