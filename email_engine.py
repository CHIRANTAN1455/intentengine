"""
Email engine (primary): max 2–3 touches; HireQuity rep tone; hiring + company context.
"""
from __future__ import annotations

import pandas as pd

from config import HIREQUITY_TONE, MAX_EMAILS_PER_LEAD
from openrouter_client import (
    OpenRouterError,
    generate_email_sequence_with_openrouter,
    suggest_role_strategy_with_openrouter,
)


def _role_hint(row: pd.Series) -> str:
    for k in ("Role", "Title", "role", "Hiring focus"):
        if k in row and pd.notna(row[k]):
            return str(row[k])
    if "Open sales roles" in row and pd.notna(row["Open sales roles"]):
        return f"your open sales hiring ({int(row['Open sales roles'])} roles)"
    return "your sales hiring"


def _company(row: pd.Series) -> str:
    return str(row.get("Company", "your team"))


def _first_name(name: str) -> str:
    n = (name or "").split()
    return n[0] if n else "there"


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


def role_based_suggestions(leads: pd.DataFrame) -> pd.DataFrame:
    """Generate role-wise personalization strategy with model fallback."""
    if leads is None or leads.empty:
        return pd.DataFrame(columns=["Role", "Count", "Angle", "Value proposition", "CTA", "Subject hook"])
    role_col = "Title" if "Title" in leads.columns else "Role"
    if role_col not in leads.columns:
        role_col = None
    if not role_col:
        return pd.DataFrame(columns=["Role", "Count", "Angle", "Value proposition", "CTA", "Subject hook"])
    rows: list[dict[str, str | int]] = []
    grouped = leads[role_col].fillna("Unknown role").astype(str).value_counts()
    for role, count in grouped.items():
        ctx = {"role": role, "lead_count": str(count), "campaign_tone": HIREQUITY_TONE}
        try:
            strat = suggest_role_strategy_with_openrouter(ctx)
        except OpenRouterError:
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


def build_email_sequence(lead: pd.Series, max_emails: int | None = None) -> list[dict[str, str]]:
    """Return list of {step, subject, body} in HireQuity voice."""
    n = max_emails or MAX_EMAILS_PER_LEAD
    n = min(max(1, n), MAX_EMAILS_PER_LEAD)
    name = str(lead.get("Name", "there"))
    co = _company(lead)
    role = _role_hint(lead)
    fn = _first_name(name)

    context = {
        "name": name,
        "company": co,
        "role_hint": role,
        "intent_reason": str(lead.get("Intent reason", "")),
        "title": str(lead.get("Title", "")),
    }
    try:
        seq = generate_email_sequence_with_openrouter(context, n)
        for item in seq:
            item["tone"] = HIREQUITY_TONE
        return seq
    except OpenRouterError:
        # Fail safe to deterministic template so outreach flow stays available.
        pass

    e1 = {
        "step": 1,
        "subject": f"Quick one — {co} and sales hiring",
        "body": (
            f"Hi {fn},\n\n"
            f"Noticed {co} is hiring for {role}. "
            f"We help teams fill those seats with pre-qualified AEs/SDRs without spamming the market.\n\n"
            f"Worth a 10-min chat this week?"
        ),
    }
    e2 = {
        "step": 2,
        "subject": f"Re: {co} / sales hiring",
        "body": (
            f"Hi {fn},\n\n"
            f"Following up — happy to share 2-3 similar placements we made for teams hiring SDRs/AEs. "
            f"If timing is off, a one-line \"not now\" works.\n\n"
            f"— HireQuity"
        ),
    }
    e3 = {
        "step": 3,
        "subject": f"Last note — {co}",
        "body": (
            f"Hi {fn},\n\n"
            f"Last ping from me. If building the sales bench is a priority, I can send a one-pager. "
            f"Otherwise I'll close the thread.\n\n"
            f"— HireQuity"
        ),
    }
    seq = [e1, e2, e3][:n]
    for e in seq:
        e["tone"] = HIREQUITY_TONE
    return seq
