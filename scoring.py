"""
Scoring: job age, number of open roles, social signals → High / Medium / Low.
Only High + Medium proceed to outreach (configurable).
"""
from __future__ import annotations

import pandas as pd

from config import (
    HIGH_INTENT_MAX_AGE_DAYS,
    MEDIUM_INTENT_MAX_AGE_DAYS,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
)


def _base_score_from_company_row(row) -> float:
    """row from merged company table with numeric fields."""
    score = 50.0
    roles = float(row.get("Open sales roles", 1) or 1)
    score += min(roles * 8, 24)  # cap boost from multiple roles
    if row.get("Has urgent (14d+)"):
        score += 12
    oldest = float(row.get("Oldest posting (days)", 0) or 0)
    score += min(oldest * 0.3, 15)
    social = int(row.get("Social signals (count)", 0) or 0)
    score += min(social * 10, 20)
    return min(score, 100.0)


def _tier_from_oldest_age(oldest_days: float) -> str:
    if oldest_days <= float(HIGH_INTENT_MAX_AGE_DAYS):
        return TIER_HIGH
    if oldest_days <= float(MEDIUM_INTENT_MAX_AGE_DAYS):
        return TIER_MEDIUM
    return TIER_LOW


def score_companies(company_df: pd.DataFrame) -> pd.DataFrame:
    if company_df.empty:
        return company_df
    out = company_df.copy()
    out["Intent score"] = out.apply(_base_score_from_company_row, axis=1)
    if "Oldest posting (days)" in out.columns:
        oldest = pd.to_numeric(out["Oldest posting (days)"], errors="coerce").fillna(MEDIUM_INTENT_MAX_AGE_DAYS + 1)
        out["Intent tier"] = oldest.map(_tier_from_oldest_age)
    else:
        out["Intent tier"] = TIER_LOW
    return out


def filter_tiers(df: pd.DataFrame, allow: tuple = (TIER_HIGH, TIER_MEDIUM)) -> pd.DataFrame:
    if df.empty or "Intent tier" not in df.columns:
        return df
    return df[df["Intent tier"].isin(allow)].copy()
