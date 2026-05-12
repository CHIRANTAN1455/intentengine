"""Role-based outreach strategy suggestions (deterministic by default; optional LLM)."""

from __future__ import annotations

from typing import Any, Dict, List, Union

import pandas as pd

from config import HIREQUITY_TONE, role_suggestions_llm_enabled
from llm_client import LLMError, suggest_role_strategy_with_llm


def _fallback_role_strategy(role: str) -> dict[str, str]:
    r = (role or "").lower()
    if "founder" in r or "ceo" in r:
        return {
            "angle": "Reduce hiring drag while keeping quality bar high.",
            "value_prop": "Shortlist faster with intent-qualified outbound candidates.",
            "cta": "Open to a 12-minute calibration call?",
            "subject_hook": "Scaling revenue team without noisy hiring",
        }
    if "vp" in r or "head of sales" in r:
        return {
            "angle": "Hit ramp targets by filling front-line sales seats sooner.",
            "value_prop": "Pipeline-ready AE/SDR profiles aligned to your stage.",
            "cta": "Should I send 3 relevant profiles this week?",
            "subject_hook": "Faster AE/SDR ramp at your stage",
        }
    if "talent" in r or "people" in r or "hr" in r:
        return {
            "angle": "Lower recruiting load on your internal hiring team.",
            "value_prop": "Pre-qualified sales candidates with less screening overhead.",
            "cta": "Want a quick process walkthrough?",
            "subject_hook": "Reducing sales hiring ops overhead",
        }
    return {
        "angle": "Support current hiring push with better-fit sales candidates.",
        "value_prop": "Role-aligned candidates sourced from high-intent signals.",
        "cta": "Worth a short intro call?",
        "subject_hook": "Sales hiring support for current openings",
    }


def role_based_suggestions(leads: Any) -> Any:
    """Generate role-wise personalization strategy with model fallback."""
    if leads is None or leads.empty:
        return pd.DataFrame(columns=["Role", "Count", "Angle", "Value proposition", "CTA", "Subject hook"])
    role_col = "Title" if "Title" in leads.columns else "Role"
    if role_col not in leads.columns:
        role_col = None
    if not role_col:
        return pd.DataFrame(columns=["Role", "Count", "Angle", "Value proposition", "CTA", "Subject hook"])
    rows: List[Dict[str, Union[str, int]]] = []
    grouped = leads[role_col].fillna("Unknown role").astype(str).value_counts()
    llm_on = role_suggestions_llm_enabled()
    for role, count in grouped.items():
        ctx = {"role": role, "lead_count": str(count), "campaign_tone": HIREQUITY_TONE}
        if llm_on:
            try:
                strat = suggest_role_strategy_with_llm(ctx)
            except LLMError:
                strat = _fallback_role_strategy(role)
        else:
            strat = _fallback_role_strategy(role)
        rows.append(
            {
                "Role": role,
                "Count": int(count),
                "Angle": strat["angle"],
                "Value proposition": strat["value_prop"],
                "CTA": strat["cta"],
                "Subject hook": strat["subject_hook"],
            }
        )
    return pd.DataFrame(rows)
