"""Job signal utilities shared by the intent pipeline."""

from __future__ import annotations

from datetime import date
import pandas as pd


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


def _unique_join_sample(series: pd.Series, *, max_items: int, sep: str = "; ") -> str:
    """First ``max_items`` distinct non-empty string values from a column."""
    seen: list[str] = []
    for x in series.dropna():
        s = str(x).strip()
        if s and s not in seen:
            seen.append(s)
        if len(seen) >= max_items:
            break
    return sep.join(seen)


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
                "Role (sample)",
                "Location (sample)",
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
    url_series = jobs.groupby("Company")["Job URL"].apply(lambda s: " | ".join(s.head(2).astype(str)))
    g["Job URLs (sample)"] = g["Company"].map(url_series)
    role_titles = jobs.groupby("Company")["Role"].apply(lambda s: _unique_join_sample(s, max_items=3))
    g["Role (sample)"] = g["Company"].map(role_titles)
    if "Location" in jobs.columns:
        locs = jobs.groupby("Company")["Location"].apply(lambda s: _unique_join_sample(s, max_items=2))
        g["Location (sample)"] = g["Company"].map(locs)
    else:
        g["Location (sample)"] = ""
    return g
