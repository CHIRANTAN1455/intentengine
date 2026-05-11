"""
Linear pipeline: Intent (jobs + social) → company merge → scoring →
 downstream steps consume the same DataFrame shape.
"""
from __future__ import annotations

import pandas as pd

from config import MAX_JOB_POSTING_AGE_DAYS
from intent_engine import add_job_signals, aggregate_by_company
from internal_intent import fetch_job_postings, fetch_social_intent
from scoring import filter_tiers, score_companies


def filter_job_postings_by_max_age(jobs: pd.DataFrame, max_age_days: int) -> pd.DataFrame:
    """Drop rows whose posting is older than max_age_days (capped at MAX_JOB_POSTING_AGE_DAYS)."""
    if jobs.empty or "Job age (days)" not in jobs.columns:
        return jobs
    cap = max(1, min(int(max_age_days), MAX_JOB_POSTING_AGE_DAYS))
    return jobs[jobs["Job age (days)"] <= cap].copy()


def _intent_reason_row(r: pd.Series) -> str:
    parts: list[str] = []
    if "Open sales roles" in r and pd.notna(r.get("Open sales roles")):
        parts.append(f"{int(r['Open sales roles'])} open sales role(s)")
    if r.get("Has urgent (14d+)"):
        parts.append("at least one role open 14+ days (urgency)")
    if r.get("Social signals (count)"):
        parts.append(f"{int(r['Social signals (count)'])} social signal(s)")
    return "; ".join(parts) if parts else "Hiring / intent from jobs + social"


def _social_counts(geo_hint: dict | None = None) -> pd.DataFrame:
    soc = fetch_social_intent(geo_hint=geo_hint)
    if soc.empty:
        return pd.DataFrame(columns=["Company", "Social signals (count)"])
    c = soc.groupby("Company", as_index=False).size()
    c = c.rename(columns={"size": "Social signals (count)"})
    return c


def run_intent_stage(
    max_job_age_days: int | None = None,
    geo_hint: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (job_postings_with_signals, company_scored).
    company_scored includes intent score + tier.

    max_job_age_days: keep only postings with job age <= this value (capped at MAX_JOB_POSTING_AGE_DAYS).
    geo_hint: optional viewer region (IP-derived) to bias synthetic corpus toward US/Canada + local area.
    """
    raw_jobs = fetch_job_postings(geo_hint=geo_hint)
    if raw_jobs.empty:
        company = pd.DataFrame()
        return raw_jobs, company

    with_signals = add_job_signals(raw_jobs)
    cap = MAX_JOB_POSTING_AGE_DAYS if max_job_age_days is None else int(max_job_age_days)
    with_signals = filter_job_postings_by_max_age(with_signals, cap)
    by_company = aggregate_by_company(with_signals)
    social = _social_counts(geo_hint=geo_hint)
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
