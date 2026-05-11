"""In-house intent ingestion powered by OpenRouter structured generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import time
from typing import Any, Callable

import pandas as pd

from config import CORPUS_NA_JOB_SHARE, INTENT_CORPUS_MIN_JOBS, SALES_ROLE_KEYWORDS
from openrouter_client import OpenRouterError, generate_intent_corpus_with_openrouter

# Per–geo-hint cache (15 min) so different viewers do not share the wrong region.
_CORPUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CORPUS_MAX_FETCH_THREADS = 3
_CORPUS_FETCH_ATTEMPTS = 3


def invalidate_intent_corpus_cache() -> None:
    global _CORPUS_CACHE
    _CORPUS_CACHE.clear()


def _corpus_cache_key(geo_hint: dict[str, Any] | None) -> str:
    if not geo_hint:
        return "default"
    return f"{str(geo_hint.get('countryCode') or '')}|{str(geo_hint.get('city') or '')}"


def _merge_corpora(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    jobs = list(base.get("jobs", []) or [])
    seen_keys = {
        (
            str(x.get("companyName") or x.get("company") or "").strip().lower(),
            str(x.get("title") or x.get("role") or "").strip().lower(),
            str(x.get("postedAt") or x.get("datePosted") or "").strip(),
        )
        for x in jobs
        if isinstance(x, dict)
    }
    for item in list(incoming.get("jobs", []) or []):
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("companyName") or item.get("company") or "").strip().lower(),
            str(item.get("title") or item.get("role") or "").strip().lower(),
            str(item.get("postedAt") or item.get("datePosted") or "").strip(),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        jobs.append(item)

    social = list(base.get("social", []) or []) + list(incoming.get("social", []) or [])
    return {"jobs": jobs, "social": social}


def _get_corpus(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    global _CORPUS_CACHE
    now = time.time()
    key = _corpus_cache_key(geo_hint)
    entry = _CORPUS_CACHE.get(key)
    if entry and now < entry[0]:
        return entry[1]
    corpus: dict[str, Any] = {"jobs": [], "social": []}
    with ThreadPoolExecutor(max_workers=_CORPUS_MAX_FETCH_THREADS) as ex:
        futures = [
            ex.submit(generate_intent_corpus_with_openrouter, geo_hint=geo_hint)
            for _ in range(_CORPUS_FETCH_ATTEMPTS)
        ]
        for fut in as_completed(futures):
            try:
                chunk = fut.result()
            except OpenRouterError:
                continue
            corpus = _merge_corpora(corpus, chunk)
            if len(list(corpus.get("jobs", []) or [])) >= INTENT_CORPUS_MIN_JOBS:
                break
    _CORPUS_CACHE[key] = (now + 15 * 60, corpus)
    return corpus


def _job_rows_from_raw_jobs(raw_jobs: list[Any]) -> list[dict[str, Any]]:
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
    return rows


def fetch_job_postings_stream(
    geo_hint: dict[str, Any] | None = None,
    on_rows: Callable[[pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    """
    Progressive fetch for UI streaming.
    Calls on_rows(partial_dataframe) after each corpus chunk.
    """
    now = time.time()
    key = _corpus_cache_key(geo_hint)
    entry = _CORPUS_CACHE.get(key)
    if entry and now < entry[0]:
        cached_jobs = _enforce_na_job_mix(list(entry[1].get("jobs", []) or []))
        df = pd.DataFrame(_job_rows_from_raw_jobs(cached_jobs))
        if on_rows is not None:
            on_rows(df)
        return df

    corpus: dict[str, Any] = {"jobs": [], "social": []}
    with ThreadPoolExecutor(max_workers=_CORPUS_MAX_FETCH_THREADS) as ex:
        futures = [
            ex.submit(generate_intent_corpus_with_openrouter, geo_hint=geo_hint)
            for _ in range(_CORPUS_FETCH_ATTEMPTS)
        ]
        for fut in as_completed(futures):
            try:
                chunk = fut.result()
            except OpenRouterError:
                continue
            corpus = _merge_corpora(corpus, chunk)
            partial_jobs = _enforce_na_job_mix(list(corpus.get("jobs", []) or []))
            partial_df = pd.DataFrame(_job_rows_from_raw_jobs(partial_jobs))
            if on_rows is not None:
                on_rows(partial_df)
            if len(partial_jobs) >= INTENT_CORPUS_MIN_JOBS:
                break

    _CORPUS_CACHE[key] = (now + 15 * 60, corpus)
    jobs = _enforce_na_job_mix(list(corpus.get("jobs", []) or []))
    return pd.DataFrame(_job_rows_from_raw_jobs(jobs))


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
    return pd.DataFrame(_job_rows_from_raw_jobs(raw_jobs))


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
