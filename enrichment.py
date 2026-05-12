"""Contact enrichment — job-board signals + optional Apollo-verified people.

Policy:
    * Zero **AI-invented** person contacts (no LLM names, emails, or phones).
    * **Job-derived fields** from the live scrape (posting titles, listing URLs,
      LinkedIn job/company links when the board returns them) are real data and
      are shown in the enrichment table.
    * **Person-level** Name / Email / Phone and LinkedIn **/in/** profile URLs
      are trusted when ``Enrichment verified`` is true after **Apollo.io**
      ``people/match`` returns a revealed email (consumes Apollo credits), or
      when a future CSV/provider path sets the flag. Otherwise those fields stay
      empty unless they pass the board-link heuristic for LinkedIn job URLs.

This module exports :func:`sanitize_enriched_dataframe` so cached / NocoDB
snapshots still strip historical fabricated person contacts (``@example.com``,
placeholder names, etc.).
"""

from __future__ import annotations

import re
from typing import Any, Callable

import pandas as pd

from apollo_enrichment import apollo_contact_enrichment_available, run_apollo_waterfall_on_dataframe

VERIFIED_CONTACT_PROVIDERS: tuple[str, ...] = ("apollo",)

# Shown on enriched rows that do not yet have a verified person to email.
CONTACT_PENDING_STATUS = "Job data — add verified email to dispatch"

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
    "sarah chen", "rahul sharma", "priya patel", "amit verma",
}
_FAKE_LINKEDIN = re.compile(
    r"linkedin\.com/(in|company)/(example|test|placeholder|sample|company-x|user-x)\b",
    re.IGNORECASE,
)

# Person-level contact columns cleared when the row is not verified.
_PERSON_CONTACT_COLUMNS = ("Name", "Email", "Phone")


def job_board_linkedin_safe(url: Any) -> bool:
    """True for LinkedIn **job listing** or **company** URLs from boards (not /in/ profiles)."""
    u = str(url or "").strip().lower()
    if "linkedin.com" not in u:
        return False
    if "/in/" in u:
        return False
    if "/jobs/" in u or "/job/" in u or "/company/" in u:
        return True
    return False


def _linkedin_from_job_urls_sample(sample: Any) -> str:
    for part in str(sample or "").split("|"):
        chunk = part.strip()
        if job_board_linkedin_safe(chunk):
            return chunk
    return ""


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
    digits = re.sub(r"\D", "", ph)
    if ph and digits and (len(digits) < 7 or len(set(digits)) <= 2):
        return True

    return False


def sanitize_enriched_dataframe(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Strip fabricated **person** contacts; keep job-board Title / URLs / board LinkedIn."""
    if df is None or len(df) == 0:
        return df
    out = df.copy()
    if "Enrichment verified" not in out.columns:
        out["Enrichment verified"] = False
    if "Contact status" not in out.columns:
        out["Contact status"] = ""

    verified_s = out["Enrichment verified"].astype(bool)

    def _fabricated_row(row: pd.Series) -> bool:
        return _looks_fabricated(
            row.get("Name"),
            row.get("Email"),
            row.get("LinkedIn"),
            row.get("Phone"),
        )

    fabricated_s = out.apply(_fabricated_row, axis=1)
    # Rows that must not keep person-level contact fields as-is.
    mask_problem = (~verified_s) | (verified_s & fabricated_s)

    for col in _PERSON_CONTACT_COLUMNS:
        if col in out.columns:
            out.loc[mask_problem, col] = ""

    if "LinkedIn" in out.columns:
        li_vals = out["LinkedIn"].fillna("").astype(str)
        keep_board = li_vals.apply(job_board_linkedin_safe)
        # Unverified: keep only board-derived LinkedIn URLs. Verified+fabricated: strip all LinkedIn.
        li_blank = mask_problem & (verified_s | ~keep_board)
        out.loc[li_blank, "LinkedIn"] = ""

    out.loc[mask_problem, "Enrichment verified"] = False
    out.loc[mask_problem, "Contact status"] = CONTACT_PENDING_STATUS
    if "Contact source" in out.columns:
        out.loc[mask_problem, "Contact source"] = ""

    out["Enrichment verified"] = out["Enrichment verified"].astype(bool)
    return out


def _job_role_for_company(row: pd.Series) -> str:
    """Open-role line from the scored company row (job board aggregation)."""
    for key in ("Role (sample)", "Role", "Hiring role", "Title"):
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


def waterfall_enrichment(
    company_or_leads: pd.DataFrame,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    """Merge company-level job signals, then optionally Apollo person + email.

    * **Hiring role** — posting title(s) from the scrape (kept on every row).
    * **Title** — same as hiring role until Apollo fills the decision-maker title.
    * **Job URLs** — sample listing URLs from the boards.
    * **LinkedIn** — job/company board URL until Apollo returns a person profile URL.
    * **Name / Email / Phone** — from Apollo when ``APOLLO_API_KEY`` is set (bounded
      batch per run); never LLM-invented.
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
        role_line = _job_role_for_company(r)
        urls = str(r.get("Job URLs (sample)") or "").strip()
        li_board = _linkedin_from_job_urls_sample(urls)

        row_out: dict = {
            "Name": "",
            "Title": role_line,
            "Company": company,
            "Email": "",
            "Phone": "",
            "LinkedIn": li_board,
            "Hiring role": role_line,
            "Contact source": "",
            "Enrichment verified": False,
            "Contact status": CONTACT_PENDING_STATUS,
            "Intent reason": intent_reason or "Hiring signals from verified job boards",
        }
        if urls:
            row_out["Job URLs"] = urls
        if "Location (sample)" in company_or_leads.columns:
            loc = str(r.get("Location (sample)") or "").strip()
            if loc:
                row_out["Location (sample)"] = loc
        if "Intent tier" in company_or_leads.columns:
            row_out["Intent tier"] = str(r.get("Intent tier") or "")
        if "Intent score" in company_or_leads.columns:
            try:
                row_out["Intent score"] = float(r.get("Intent score") or 0.0)
            except (TypeError, ValueError):
                row_out["Intent score"] = 0.0
        if "Open sales roles" in company_or_leads.columns:
            try:
                row_out["Open sales roles"] = int(r.get("Open sales roles") or 0)
            except (TypeError, ValueError):
                row_out["Open sales roles"] = 0
        rows.append(row_out)

    df = pd.DataFrame(rows)
    if apollo_contact_enrichment_available() and not df.empty:
        merged = run_apollo_waterfall_on_dataframe(
            df.to_dict(orient="records"),
            on_progress=on_progress,
        )
        df = pd.DataFrame(merged)
    return sanitize_enriched_dataframe(df)


def lead_has_verified_contact(lead: pd.Series | dict) -> bool:
    """True when a real person contact is verified (not job-board URLs alone)."""
    verified = bool(lead.get("Enrichment verified"))
    email = str(lead.get("Email") or "").strip()
    name = str(lead.get("Name") or "").strip()
    if not verified or not email or not name:
        return False
    if _looks_fabricated(name, email, lead.get("LinkedIn"), lead.get("Phone")):
        return False
    return True
