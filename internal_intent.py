"""In-house intent ingestion powered by OpenRouter structured generation."""

from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any

import pandas as pd

from config import CORPUS_NA_JOB_SHARE, SALES_ROLE_KEYWORDS
from openrouter_client import OpenRouterError, generate_intent_corpus_with_openrouter

# Per–geo-hint cache (15 min) so different viewers do not share the wrong region.
_CORPUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def invalidate_intent_corpus_cache() -> None:
    global _CORPUS_CACHE
    _CORPUS_CACHE.clear()


def _corpus_cache_key(geo_hint: dict[str, Any] | None) -> str:
    if not geo_hint:
        return "default"
    return f"{str(geo_hint.get('countryCode') or '')}|{str(geo_hint.get('city') or '')}"


def _get_corpus(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    global _CORPUS_CACHE
    now = time.time()
    key = _corpus_cache_key(geo_hint)
    entry = _CORPUS_CACHE.get(key)
    if entry and now < entry[0]:
        return entry[1]
    try:
        corpus = generate_intent_corpus_with_openrouter(geo_hint=geo_hint)
    except OpenRouterError:
        corpus = {"jobs": [], "social": []}
    _CORPUS_CACHE[key] = (now + 15 * 60, corpus)
    return corpus


def _enforce_na_job_mix(jobs: list[Any]) -> list[Any]:
    """If countryCode is mostly present, trim non-US/CA rows to ~5% cap."""
    if not jobs:
        return jobs
    eligible = [j for j in jobs if isinstance(j, dict)]
    if not eligible:
        return jobs
    with_cc = sum(1 for j in eligible if str(j.get("countryCode") or "").strip())
    if with_cc < max(3, len(eligible) // 2):
        return jobs
    na: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for j in eligible:
        cc = str(j.get("countryCode") or "").strip().upper()
        if cc in ("US", "CA", ""):
            na.append(j)
        else:
            other.append(j)
    n = len(eligible)
    max_other = max(0, int(n * (1.0 - CORPUS_NA_JOB_SHARE) + 0.999))
    if len(other) <= max_other:
        return jobs
    if not na:
        return jobs
    return na + other[:max_other]


def _is_sales_role(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in SALES_ROLE_KEYWORDS)


def _parse_posted_date(raw: str | None) -> date:
    if not raw:
        return date.today() - timedelta(days=7)
    text = str(raw).strip()
    for sep in ("T", " "):
        if sep in text:
            text = text.split(sep)[0]
            break
    try:
        return date.fromisoformat(text)
    except ValueError:
        return date.today() - timedelta(days=7)


def fetch_job_postings(geo_hint: dict[str, Any] | None = None) -> pd.DataFrame:
    corpus = _get_corpus(geo_hint)
    raw_jobs = list(corpus.get("jobs", []) or [])
    raw_jobs = _enforce_na_job_mix(raw_jobs)
    rows: list[dict[str, Any]] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        role = str(item.get("title") or item.get("role") or "")
        company = str(item.get("companyName") or item.get("company") or "").strip()
        if not company or not role or not _is_sales_role(role):
            continue
        rows.append(
            {
                "Company": company,
                "Role": role,
                "Job URL": str(item.get("url") or item.get("jobUrl") or ""),
                "Posting date": _parse_posted_date(item.get("postedAt") or item.get("datePosted")),
                "Source": str(item.get("source") or "inhouse_openrouter"),
                "Country code": str(item.get("countryCode") or "").strip().upper(),
            }
        )
    return pd.DataFrame(rows)


def fetch_social_intent(geo_hint: dict[str, Any] | None = None) -> pd.DataFrame:
    corpus = _get_corpus(geo_hint)
    rows: list[dict[str, Any]] = []
    for item in corpus.get("social", []) or []:
        if not isinstance(item, dict):
            continue
        company = str(item.get("companyName") or item.get("company") or "").strip()
        signal = str(item.get("text") or item.get("signal") or item.get("content") or "").strip()
        if not company or not signal:
            continue
        rows.append(
            {
                "Company": company,
                "Signal": signal,
                "Source": str(item.get("source") or "inhouse_openrouter"),
            }
        )
    return pd.DataFrame(rows)
