"""
Waterfall enrichment: decision-makers (VP Sales, Head of Sales, Founder, HR)
until verified contact (V1: simulated).
"""
from __future__ import annotations

import hashlib
import re
import pandas as pd

DECISION_TITLES = [
    "VP Sales",
    "Head of Sales",
    "Founder",
    "Head of Talent",
    "HR / People",
]


def _fake_email(name: str, company: str) -> str:
    n = re.sub(r"[^a-zA-Z ]", "", name or "contact").strip().lower().replace(" ", ".")
    c = re.sub(r"[^a-zA-Z0-9]", "", (company or "company").lower())[:24]
    return f"{n}@{c}.com" if n else f"hi@{c}.com"


def _fake_linkedin(name: str) -> str:
    handle = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "user").lower()).strip("-")
    return f"https://linkedin.com/in/{handle or 'user'}"


def waterfall_enrichment(company_or_leads: pd.DataFrame) -> pd.DataFrame:
    """
    Input: rows with at least 'Company' (from intent pipeline) OR legacy lead rows
    with Name, Company, etc.
    Output: enriched contact rows per company/lead.
    """
    if company_or_leads.empty:
        return company_or_leads

    # Legacy shape (Name column): keep current behavior, add fields
    if "Name" in company_or_leads.columns and "Company" in company_or_leads.columns:
        df = company_or_leads.copy()
    elif "Company" in company_or_leads.columns:
        # Company-level: synthesize one decision-maker per company row
        rows = []
        for _, r in company_or_leads.iterrows():
            co = r["Company"]
            h = int(hashlib.md5(str(co).encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
            title = DECISION_TITLES[h % len(DECISION_TITLES)]
            first = str(co)[:1] + " lead"
            name = f"Alex {co.split()[0] if co else 'Contact'}"[:32]
            rows.append(
                {
                    "Name": name,
                    "Title": title,
                    "Company": co,
                    "Email": r.get("Email") if "Email" in r and pd.notna(r.get("Email")) else _fake_email(name, co),
                    "Phone": "+1-415-555-0100",
                    "LinkedIn": _fake_linkedin(name),
                    "Enrichment verified": True,
                    "Intent reason": r.get("Intent reason", "Hiring sales + signals"),
                }
            )
        df = pd.DataFrame(rows)
    else:
        return company_or_leads

    for col in ("Phone", "LinkedIn", "Enrichment verified", "Intent reason"):
        if col not in df.columns:
            df[col] = None
    for i, row in df.iterrows():
        if pd.isna(row.get("Email")) or row.get("Email") in ("", None):
            df.at[i, "Email"] = _fake_email(str(row.get("Name", "")), str(row.get("Company", "")))
        if pd.isna(row.get("Phone")) or not row.get("Phone"):
            df.at[i, "Phone"] = "+1-415-555-0100"
        if pd.isna(row.get("LinkedIn")) or not row.get("LinkedIn"):
            df.at[i, "LinkedIn"] = _fake_linkedin(str(row.get("Name", "")))
        df.at[i, "Enrichment verified"] = True
        if pd.isna(row.get("Intent reason")) or not row.get("Intent reason"):
            df.at[i, "Intent reason"] = "Hiring for sales; intent signals from jobs/social"
    return df
