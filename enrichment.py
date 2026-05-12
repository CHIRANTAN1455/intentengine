"""Contact enrichment — verified sources only.

Policy (set by the client, May 2026):
    * Zero AI-generated contacts.
    * Surface contact fields only when they come from a verified provider
      (Apollo, Hunter, ZoomInfo, etc.). Otherwise leave them blank/null.
    * Job + company data (Company, Role, Job URL, etc.) is sourced from the
      live job-board scrape and *is* verified — we keep it as-is.

This module previously asked an LLM to invent a decision-maker per company.
That logic is gone. Until a real verification provider is wired in, the
enrichment step is effectively "carry through verified job-derived data and
mark the contact as awaiting verification".
"""

from __future__ import annotations

import pandas as pd

VERIFIED_CONTACT_PROVIDERS: tuple[str, ...] = ()  # populate when a provider is integrated

# Status string surfaced on the lead + CRM row so SDRs immediately know that
# the contact still needs a verified source before any outreach.
CONTACT_PENDING_STATUS = "Awaiting verified contact"


def _job_role_for_company(row: pd.Series) -> str:
    """Return the verified open-role string from the scored row, if present."""
    for key in ("Role", "Hiring role", "Title"):
        if key in row and pd.notna(row.get(key)):
            v = str(row.get(key) or "").strip()
            if v:
                return v
    if "Open sales roles" in row and pd.notna(row.get("Open sales roles")):
        try:
            n = int(row.get("Open sales roles") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return f"{n} open sales role(s)"
    return ""


def waterfall_enrichment(company_or_leads: pd.DataFrame) -> pd.DataFrame:
    """Pass companies through the enrichment step with verified data only.

    Output columns:
        Name / Email / Phone / LinkedIn       -> blank until a verified provider fills them
        Title (decision-maker title)          -> blank for the same reason
        Hiring role (verified open role)      -> carried from the scraped posting
        Company / Intent reason / tier / score -> carried through from scoring
        Enrichment verified                   -> always False until a provider verifies
        Contact status                        -> "Awaiting verified contact"
    """
    if company_or_leads is None or company_or_leads.empty:
        return pd.DataFrame()
    if "Company" not in company_or_leads.columns:
        return company_or_leads

    rows: list[dict] = []
    for _, r in company_or_leads.iterrows():
        company = str(r.get("Company") or "").strip()
        if not company:
            continue
        intent_reason = str(r.get("Intent reason", "") or "")
        hiring_role = _job_role_for_company(r)

        row_out: dict = {
            "Name": "",
            "Title": "",
            "Company": company,
            "Email": "",
            "Phone": "",
            "LinkedIn": "",
            "Hiring role": hiring_role,
            "Enrichment verified": False,
            "Contact status": CONTACT_PENDING_STATUS,
            "Intent reason": intent_reason or "Hiring signals from verified job boards",
        }
        if "Intent tier" in company_or_leads.columns:
            row_out["Intent tier"] = str(r.get("Intent tier") or "")
        if "Intent score" in company_or_leads.columns:
            try:
                row_out["Intent score"] = float(r.get("Intent score") or 0.0)
            except (TypeError, ValueError):
                row_out["Intent score"] = 0.0
        rows.append(row_out)
    return pd.DataFrame(rows)


def lead_has_verified_contact(lead: pd.Series | dict) -> bool:
    """True only when a real verification provider has confirmed the contact."""
    if isinstance(lead, pd.Series):
        verified = bool(lead.get("Enrichment verified"))
        email = str(lead.get("Email") or "").strip()
    else:
        verified = bool(lead.get("Enrichment verified"))
        email = str(lead.get("Email") or "").strip()
    return verified and bool(email)
