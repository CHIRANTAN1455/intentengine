"""
Intent Engine (V1): job postings from LinkedIn Jobs, Indeed, Glassdoor (simulated data).
Output: intent-scored company list with job age, role count, urgency signals.
"""
from __future__ import annotations

from datetime import date, timedelta
import pandas as pd

from config import SALES_ROLE_KEYWORDS

# V1: deterministic mock “scrape” — swap with real API/scraper in production.
_MOCK_JOBS: list[dict] = [
    {
        "company": "Nexora",
        "role": "SDR (Outbound)",
        "job_url": "https://example.com/jobs/nexora-sdr-1",
        "posted_date": date.today() - timedelta(days=18),
        "source": "linkedin_jobs",
    },
    {
        "company": "Nexora",
        "role": "Account Executive",
        "job_url": "https://example.com/jobs/nexora-ae-1",
        "posted_date": date.today() - timedelta(days=9),
        "source": "indeed",
    },
    {
        "company": "PulseLabs",
        "role": "BDR",
        "job_url": "https://example.com/jobs/pulselabs-bdr",
        "posted_date": date.today() - timedelta(days=5),
        "source": "glassdoor",
    },
    {
        "company": "ScaleHire",
        "role": "Account Executive (SMB)",
        "job_url": "https://example.com/jobs/scalehire-ae",
        "posted_date": date.today() - timedelta(days=22),
        "source": "linkedin_jobs",
    },
    {
        "company": "TribeWorks",
        "role": "Marketing Manager",  # filtered out (not sales)
        "job_url": "https://example.com/jobs/tribe-mkt",
        "posted_date": date.today() - timedelta(days=3),
        "source": "indeed",
    },
]


def _is_sales_role(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in SALES_ROLE_KEYWORDS)


def fetch_job_postings() -> pd.DataFrame:
    """
    Returns one row per job posting: Company, Role, Job URL, Posting date, Source.
    """
    rows = []
    for j in _MOCK_JOBS:
        if not _is_sales_role(j["role"]):
            continue
        rows.append(
            {
                "Company": j["company"],
                "Role": j["role"],
                "Job URL": j["job_url"],
                "Posting date": j["posted_date"],
                "Source": j["source"],
            }
        )
    return pd.DataFrame(rows)


def add_job_signals(jobs: pd.DataFrame) -> pd.DataFrame:
    """Per posting: job age (days), urgency (role open >14d), feed for aggregation."""
    if jobs.empty:
        return jobs
    out = jobs.copy()
    today = date.today()
    ps = pd.to_datetime(out["Posting date"]).dt.date
    out["Job age (days)"] = [(today - p).days for p in ps]
    out["Urgent (role >14d)"] = out["Job age (days)"] > 14
    return out


def aggregate_by_company(jobs: pd.DataFrame) -> pd.DataFrame:
    """Company-level: open sales roles count, min/max age, any urgent."""
    if jobs.empty:
        return pd.DataFrame(
            columns=[
                "Company",
                "Open sales roles",
                "Oldest posting (days)",
                "Newest posting (days)",
                "Has urgent (14d+)",
                "Job URLs (sample)",
            ]
        )
    g = (
        jobs.groupby("Company", as_index=False)
        .agg(
            Open_sales_roles=("Role", "count"),
            Oldest_posting_days=("Job age (days)", "max"),
            Newest_posting_days=("Job age (days)", "min"),
            Has_urgent=("Urgent (role >14d)", "any"),
        )
    )
    g = g.rename(
        columns={
            "Open_sales_roles": "Open sales roles",
            "Oldest_posting_days": "Oldest posting (days)",
            "Newest_posting_days": "Newest posting (days)",
            "Has_urgent": "Has urgent (14d+)",
        }
    )
    # sample URL list
    url_series = jobs.groupby("Company")["Job URL"].apply(lambda s: " | ".join(s.head(2).astype(str)))
    g["Job URLs (sample)"] = g["Company"].map(url_series)
    return g
