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

It also exports :func:`sanitize_enriched_dataframe` so any cached / hydrated
enrichment payload (e.g. from a NocoDB snapshot saved before the migration)
gets retroactively scrubbed of fabricated values on load.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

VERIFIED_CONTACT_PROVIDERS: tuple[str, ...] = ()  # populate when a provider is integrated

# Status string surfaced on the lead + CRM row so SDRs immediately know that
# the contact still needs a verified source before any outreach.
CONTACT_PENDING_STATUS = "Awaiting verified contact"

# Patterns that the old fabricator / LLM used. Any row matching these is
# always treated as unverified and stripped, regardless of what flag the
# stored snapshot may carry.
_FAKE_EMAIL_DOMAINS = re.compile(
    r"@("
    r"example\.com|example\.org|example\.net|test\.com|sample\.com|"
    r"placeholder\.com|localhost|"
    r".*\.example\.com|.*\.example\.org"
    r")\b",
    re.IGNORECASE,
)
_FAKE_NAME_PHRASES = {
    "alex rivera", "alex patel", "alex nguyen", "alex brooks",
    "sam rivera", "sam patel", "sam nguyen", "sam brooks",
    "jordan rivera", "jordan patel", "jordan nguyen", "jordan brooks",
    "casey rivera", "casey patel", "casey nguyen", "casey brooks",
    # leads.py mock data
    "sarah chen", "rahul sharma", "priya patel", "amit verma",
}
_FAKE_LINKEDIN = re.compile(
    r"linkedin\.com/(in|company)/(example|test|placeholder|sample|company-x|user-x)\b",
    re.IGNORECASE,
)


def _looks_fabricated(
    name: Any,
    email: Any,
    linkedin: Any,
    phone: Any,
) -> bool:
    """Heuristics for the historical fabricated-contact patterns."""
    em = (str(email) if email is not None else "").strip()
    if em and _FAKE_EMAIL_DOMAINS.search(em):
        return True

    nm = (str(name) if name is not None else "").strip().lower()
    if nm and nm in _FAKE_NAME_PHRASES:
        return True

    li = (str(linkedin) if linkedin is not None else "").strip()
    if li and _FAKE_LINKEDIN.search(li):
        return True

    ph = (str(phone) if phone is not None else "").strip()
    # Old fabricator produced very short / repeating placeholder numbers.
    digits = re.sub(r"\D", "", ph)
    if ph and digits and (len(digits) < 7 or len(set(digits)) <= 2):
        return True

    return False


_CONTACT_COLUMNS = ("Name", "Email", "Phone", "LinkedIn", "Title")


def sanitize_enriched_dataframe(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Strip any fabricated contact data and force ``Enrichment verified = False``.

    Run on every enrichment payload — fresh, cached, or hydrated from NocoDB —
    so old snapshots (Sarah Chen / Priya Patel / `@example.com`) get scrubbed
    automatically the next time the app loads.
    """
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    if "Enrichment verified" not in out.columns:
        out["Enrichment verified"] = False
    if "Contact status" not in out.columns:
        out["Contact status"] = ""

    def _row_unverified(row: pd.Series) -> bool:
        if not bool(row.get("Enrichment verified")):
            return True
        return _looks_fabricated(
            row.get("Name"),
            row.get("Email"),
            row.get("LinkedIn"),
            row.get("Phone"),
        )

    mask_blank = out.apply(_row_unverified, axis=1)
    for col in _CONTACT_COLUMNS:
        if col in out.columns:
            out.loc[mask_blank, col] = ""
    out.loc[mask_blank, "Enrichment verified"] = False
    out.loc[mask_blank, "Contact status"] = CONTACT_PENDING_STATUS

    # On rows that survive as verified, normalise dtype so later code paths
    # (mask + dispatch) never trip on numpy.bool_ vs python bool.
    out["Enrichment verified"] = out["Enrichment verified"].astype(bool)
    return out


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
    return sanitize_enriched_dataframe(pd.DataFrame(rows))


def lead_has_verified_contact(lead: pd.Series | dict) -> bool:
    """True only when a real verification provider has confirmed the contact."""
    verified = bool(lead.get("Enrichment verified"))
    email = str(lead.get("Email") or "").strip()
    name = str(lead.get("Name") or "").strip()
    if not verified or not email or not name:
        return False
    # Even if the stored flag is True, refuse to dispatch when the values
    # look like the historical fabricator output.
    if _looks_fabricated(name, email, lead.get("LinkedIn"), lead.get("Phone")):
        return False
    return True
