"""
Email engine (primary): max 2–3 touches; HireQuity rep tone; hiring + company context.
"""
from __future__ import annotations

import pandas as pd

from config import HIREQUITY_TONE, MAX_EMAILS_PER_LEAD


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


def build_email_sequence(lead: pd.Series, max_emails: int | None = None) -> list[dict[str, str]]:
    """Return list of {step, subject, body} in HireQuity voice."""
    n = max_emails or MAX_EMAILS_PER_LEAD
    n = min(max(1, n), MAX_EMAILS_PER_LEAD)
    name = str(lead.get("Name", "there"))
    co = _company(lead)
    role = _role_hint(lead)
    fn = _first_name(name)

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
