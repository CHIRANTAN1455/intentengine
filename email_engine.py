"""Email engine — deterministic templates by default.

We removed the per-lead LLM call that was the main latency offender (≈ 1
network round trip per lead × N leads on every "Outreach" render). The
deterministic templates are instant, never hallucinate a name, and only
reference verified data (Company + Hiring role + Intent reason).

If an operator explicitly opts in by setting ``EMAIL_LLM_AUGMENT=1`` we will
augment with the LLM, but the safe default is OFF.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from config import HIREQUITY_TONE, MAX_EMAILS_PER_LEAD, email_llm_augment_enabled
from llm_client import LLMError, generate_email_sequence_with_llm


GENERIC_GREETING = "Hi there,"


def _role_hint(row: pd.Series) -> str:
    for k in ("Hiring role", "Role", "role"):
        if k in row and pd.notna(row[k]):
            v = str(row[k]).strip()
            if v:
                return v
    if "Open sales roles" in row and pd.notna(row["Open sales roles"]):
        try:
            return f"your open sales hiring ({int(row['Open sales roles'])} roles)"
        except (TypeError, ValueError):
            pass
    return "your sales hiring"


def _company(row: pd.Series) -> str:
    co = str(row.get("Company", "") or "").strip()
    return co or "your team"


def _greeting(row: pd.Series) -> str:
    """Greeting that never invents a first name.

    We only personalize when there is a verified contact name. Otherwise we
    use a neutral greeting — this is the verified-data-only policy.
    """
    verified = bool(row.get("Enrichment verified"))
    name = str(row.get("Name") or "").strip()
    if verified and name:
        first = name.split()[0]
        return f"Hi {first},"
    return GENERIC_GREETING


def _default_sequence(lead: pd.Series, n: int) -> List[Dict[str, str]]:
    co = _company(lead)
    role = _role_hint(lead)
    greeting = _greeting(lead)
    e1 = {
        "step": 1,
        "subject": f"Quick one — {co} and sales hiring",
        "body": (
            f"{greeting}\n\n"
            f"Noticed {co} is hiring for {role}. We help teams fill those seats "
            "with pre-qualified AEs/SDRs without spamming the market.\n\n"
            "Worth a 10-minute chat this week?"
        ),
    }
    e2 = {
        "step": 2,
        "subject": f"Re: {co} / sales hiring",
        "body": (
            f"{greeting}\n\n"
            "Following up — happy to share 2–3 similar placements we made for "
            "teams hiring SDRs/AEs. If timing is off, a one-line \"not now\" works.\n\n"
            "— hirequity"
        ),
    }
    e3 = {
        "step": 3,
        "subject": f"Last note — {co}",
        "body": (
            f"{greeting}\n\n"
            "Last ping from me. If building the sales bench is a priority, I can "
            "send a one-pager. Otherwise I'll close the thread.\n\n"
            "— hirequity"
        ),
    }
    return [e1, e2, e3][:n]


def build_email_sequence(lead: pd.Series, max_emails: Optional[int] = None) -> List[Dict[str, str]]:
    """Return list of ``{step, subject, body, tone}`` for an outreach sequence.

    Deterministic by default. Falls back to the deterministic templates if the
    optional LLM augmentation is enabled but fails.
    """
    n = max_emails or MAX_EMAILS_PER_LEAD
    n = min(max(1, int(n)), MAX_EMAILS_PER_LEAD)

    if not email_llm_augment_enabled():
        seq = _default_sequence(lead, n)
        for item in seq:
            item["tone"] = HIREQUITY_TONE
        return seq

    context = {
        "company": _company(lead),
        "role_hint": _role_hint(lead),
        "intent_reason": str(lead.get("Intent reason", "")),
        "has_verified_name": "true" if bool(lead.get("Enrichment verified")) and str(lead.get("Name") or "").strip() else "false",
    }
    try:
        seq = generate_email_sequence_with_llm(context, n)
        for item in seq:
            item["tone"] = HIREQUITY_TONE
        return seq
    except LLMError:
        seq = _default_sequence(lead, n)
        for item in seq:
            item["tone"] = HIREQUITY_TONE
        return seq
