"""
Linear pipeline: Intent (jobs + social) → company merge → scoring →
 downstream steps consume the same DataFrame shape.
"""
from __future__ import annotations

import pandas as pd

from intent_engine import add_job_signals, aggregate_by_company
from internal_intent import fetch_job_postings, fetch_social_intent
from scoring import filter_tiers, score_companies


def _intent_reason_row(r: pd.Series) -> str:
    parts: list[str] = []
    if "Open sales roles" in r and pd.notna(r.get("Open sales roles")):
        parts.append(f"{int(r['Open sales roles'])} open sales role(s)")
    if r.get("Has urgent (14d+)"):
        parts.append("at least one role open 14+ days (urgency)")
    if r.get("Social signals (count)"):
        parts.append(f"{int(r['Social signals (count)'])} social signal(s)")
    return "; ".join(parts) if parts else "Hiring / intent from jobs + social"


def _social_counts() -> pd.DataFrame:
    soc = fetch_social_intent()
    if soc.empty:
        return pd.DataFrame(columns=["Company", "Social signals (count)"])
    c = soc.groupby("Company", as_index=False).size()
    c = c.rename(columns={"size": "Social signals (count)"})
    return c


def run_intent_stage() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (job_postings_with_signals, company_scored).
    company_scored includes intent score + tier.
    """
    raw_jobs = fetch_job_postings()
    if raw_jobs.empty:
        company = pd.DataFrame()
        return raw_jobs, company

    with_signals = add_job_signals(raw_jobs)
    by_company = aggregate_by_company(with_signals)
    social = _social_counts()
    if not social.empty:
        merged = by_company.merge(social, on="Company", how="left")
        merged["Social signals (count)"] = merged["Social signals (count)"].fillna(0).astype(int)
    else:
        merged = by_company.copy()
        merged["Social signals (count)"] = 0

    scored = score_companies(merged)
    scored["Intent reason"] = scored.apply(_intent_reason_row, axis=1)
    return with_signals, scored


def filter_outreach_ready(company_scored: pd.DataFrame) -> pd.DataFrame:
    return filter_tiers(company_scored)
