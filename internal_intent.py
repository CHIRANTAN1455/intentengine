"""Intent ingestion: live job boards first; optional LLM fallback (off by default)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import time
from typing import Any, Callable

import pandas as pd

from config import (
    CORPUS_CA_JOB_SHARE,
    CORPUS_US_JOB_SHARE,
    INTENT_CORPUS_MIN_JOBS,
    LIVE_JOB_SITES,
    MAX_JOB_POSTING_AGE_DAYS,
    SALES_ROLE_KEYWORDS,
    allow_synthetic_intent_corpus,
)
from llm_client import LLMError, generate_intent_corpus_with_llm

# Per–geo-hint cache so different viewers do not share the wrong region.
# Short TTL on purpose: identical fetches across many devices in a row used to
# repeat the same listings for 15 min; now we keep the cache only long enough
# to absorb a single user's reload burst, not a multi-device demo.
_CORPUS_CACHE_TTL_SECONDS_OK = 180
_CORPUS_CACHE_TTL_SECONDS_EMPTY = 30
_CORPUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CORPUS_MAX_FETCH_THREADS = 3
_CORPUS_FETCH_ATTEMPTS = 3

# When LinkedIn returns 429 ("too many requests"), every subsequent jobspy call
# on this process retries LinkedIn for ~60s before failing. Track a soft cooloff
# so we skip LinkedIn entirely for a short window and rely on Indeed.
_LINKEDIN_COOLOFF_UNTIL: float = 0.0
_LINKEDIN_COOLOFF_SECONDS = 10 * 60


def _linkedin_in_cooloff() -> bool:
    return time.time() < _LINKEDIN_COOLOFF_UNTIL


def _trip_linkedin_cooloff() -> None:
    global _LINKEDIN_COOLOFF_UNTIL
    _LINKEDIN_COOLOFF_UNTIL = time.time() + _LINKEDIN_COOLOFF_SECONDS


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


def _derive_social_from_jobs(raw_jobs: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for j in raw_jobs:
        company = str(j.get("companyName") or "").strip()
        role = str(j.get("title") or "").strip()
        if not company or company in seen:
            continue
        seen.add(company)
        out.append(
            {
                "companyName": company,
                "text": f"{company} is actively hiring for sales role(s) such as {role}.",
                "source": "live_job_boards",
            }
        )
    return out


def _to_iso_date(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return (date.today() - timedelta(days=7)).isoformat()
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return (date.today() - timedelta(days=7)).isoformat()
        return ts.date().isoformat()
    except Exception:
        return (date.today() - timedelta(days=7)).isoformat()


def _country_targets() -> list[tuple[str, str, str, int]]:
    """
    Returns tuples: (country_code, country_indeed, location, target_rows)
    """
    total = max(INTENT_CORPUS_MIN_JOBS, 20)
    ca_target = max(1, int(round(total * CORPUS_CA_JOB_SHARE)))
    us_target = max(1, total - ca_target)
    return [
        ("CA", "canada", "Canada", ca_target),
        ("US", "usa", "United States", us_target),
    ]


def _live_jobspy_corpus(
    geo_hint: dict[str, Any] | None = None,
    on_partial_jobs: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """
    Pull live jobs from boards via python-jobspy.
    Falls back to empty lists if dependency or upstream scraping fails.
    """
    try:
        from jobspy import scrape_jobs
    except Exception:
        return {"jobs": [], "social": []}

    roles = [
        "sales representative",
        "account executive",
        "sales development representative",
        "business development representative",
    ]
    targets = _country_targets()
    tasks: list[tuple[str, str, str, int]] = []
    for cc, indeed_country, location, target in targets:
        per_role = max(5, int(target / max(1, len(roles))))
        for role in roles:
            tasks.append((cc, indeed_country, location, per_role))

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    # inject role-specific search terms by rebuilding tasks with role in search term call
    with ThreadPoolExecutor(max_workers=_CORPUS_MAX_FETCH_THREADS) as ex:
        futures = []
        for cc, indeed_country, location, target in targets:
            per_role = max(5, int(target / max(1, len(roles))))
            for role in roles:
                futures.append(
                    ex.submit(
                        lambda c=cc, ic=indeed_country, loc=location, wanted=per_role, r=role: _run_jobspy_query(
                            c, ic, loc, wanted, r
                        )
                    )
                )
        for fut in as_completed(futures):
            try:
                batch = fut.result()
            except Exception:
                continue
            if not batch:
                continue
            for row in batch:
                company = str(row.get("companyName") or "").strip().lower()
                title = str(row.get("title") or "").strip().lower()
                url = str(row.get("url") or "").strip()
                key = (company, title, url)
                if key in seen:
                    continue
                seen.add(key)
                results.append(row)
            if on_partial_jobs is not None:
                on_partial_jobs(results.copy())
            if len(results) >= INTENT_CORPUS_MIN_JOBS:
                break

    return {"jobs": results, "social": _derive_social_from_jobs(results)}


def _run_jobspy_query(
    country_code: str,
    indeed_country: str,
    location: str,
    wanted: int,
    role_query: str,
) -> list[dict[str, Any]]:
    try:
        from jobspy import scrape_jobs
    except Exception:
        return []
    # When LinkedIn just 429'd, drop it from the site list so jobspy doesn't burn
    # ~60s retrying LinkedIn before falling through to Indeed.
    sites = [s for s in LIVE_JOB_SITES if not (_linkedin_in_cooloff() and s == "linkedin")]
    if not sites:
        sites = ["indeed"]
    kwargs: dict[str, Any] = {
        "site_name": sites,
        "search_term": role_query,
        "location": location,
        "results_wanted": max(wanted, 20),
        "hours_old": 24 * MAX_JOB_POSTING_AGE_DAYS,
        "country_indeed": indeed_country,
    }
    try:
        try:
            df = scrape_jobs(**kwargs, linkedin_fetch_description=True)
        except TypeError:
            df = scrape_jobs(**kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "too many" in msg or "linkedin" in msg:
            _trip_linkedin_cooloff()
        return []
    if df is None or len(df) == 0:
        return []
    out_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        company = str(row.get("company") or row.get("company_name") or "").strip()
        title = str(row.get("title") or "").strip()
        url = str(row.get("job_url") or row.get("url") or "").strip()
        if not company or not title:
            continue
        if not _is_sales_role(title):
            continue
        desc = str(
            row.get("description")
            or row.get("job_description")
            or row.get("summary")
            or ""
        ).strip()
        if len(desc) > 4000:
            desc = desc[:4000] + "…"
        loc = str(row.get("location") or row.get("job_location") or "").strip()
        out_rows.append(
            {
                "companyName": company,
                "title": title,
                "url": url,
                "postedAt": _to_iso_date(row.get("date_posted")),
                "countryCode": country_code,
                "source": str(row.get("site") or "live_job_boards"),
                "location": loc,
                "listingSnippet": desc,
            }
        )
    return out_rows


def _get_corpus(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    global _CORPUS_CACHE
    now = time.time()
    key = _corpus_cache_key(geo_hint)
    entry = _CORPUS_CACHE.get(key)
    if entry and now < entry[0]:
        return entry[1]
    corpus = _live_jobspy_corpus(geo_hint=geo_hint)
    if (
        len(list(corpus.get("jobs", []) or [])) < max(15, int(INTENT_CORPUS_MIN_JOBS * 0.35))
        and allow_synthetic_intent_corpus()
    ):
        # Synthetic LLM-generated job listings are *only* allowed when the
        # operator opts in via ALLOW_SYNTHETIC_INTENT_CORPUS=1. By default this
        # branch never runs so the pipeline only surfaces verified board data.
        corpus = {"jobs": [], "social": []}
        with ThreadPoolExecutor(max_workers=_CORPUS_MAX_FETCH_THREADS) as ex:
            futures = [
                ex.submit(generate_intent_corpus_with_llm, geo_hint=geo_hint)
                for _ in range(_CORPUS_FETCH_ATTEMPTS)
            ]
            for fut in as_completed(futures):
                try:
                    chunk = fut.result()
                except LLMError:
                    continue
                corpus = _merge_corpora(corpus, chunk)
                if len(list(corpus.get("jobs", []) or [])) >= INTENT_CORPUS_MIN_JOBS:
                    break
    job_n = len(list(corpus.get("jobs", []) or []))
    ttl = _CORPUS_CACHE_TTL_SECONDS_OK if job_n > 0 else _CORPUS_CACHE_TTL_SECONDS_EMPTY
    _CORPUS_CACHE[key] = (now + ttl, corpus)
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
        row_out: dict[str, Any] = {
            "Company": company,
            "Role": role,
            "Job URL": str(item.get("url") or item.get("jobUrl") or ""),
            "Posting date": _parse_posted_date(item.get("postedAt") or item.get("datePosted")),
            "Source": str(item.get("source") or "live_job_boards"),
            "Country code": str(item.get("countryCode") or "").strip().upper(),
        }
        loc = str(item.get("location") or "").strip()
        if loc:
            row_out["Location"] = loc[:500]
        snip = str(item.get("listingSnippet") or item.get("description") or "").strip()
        if snip:
            row_out["Listing snippet"] = snip[:4000]
        rows.append(row_out)
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
        cached_jobs = _enforce_country_priority_mix(list(entry[1].get("jobs", []) or []))
        df = pd.DataFrame(_job_rows_from_raw_jobs(cached_jobs))
        if on_rows is not None:
            on_rows(df)
        return df

    def _on_partial(raw_jobs: list[dict[str, Any]]) -> None:
        if on_rows is None:
            return
        partial_jobs = _enforce_country_priority_mix(raw_jobs)
        partial_df = pd.DataFrame(_job_rows_from_raw_jobs(partial_jobs))
        on_rows(partial_df)

    corpus = _live_jobspy_corpus(geo_hint=geo_hint, on_partial_jobs=_on_partial)
    if (
        len(list(corpus.get("jobs", []) or [])) < max(15, int(INTENT_CORPUS_MIN_JOBS * 0.35))
        and allow_synthetic_intent_corpus()
    ):
        # Synthetic LLM corpus is opt-in only (ALLOW_SYNTHETIC_INTENT_CORPUS=1).
        corpus = {"jobs": [], "social": []}
        with ThreadPoolExecutor(max_workers=_CORPUS_MAX_FETCH_THREADS) as ex:
            futures = [
                ex.submit(generate_intent_corpus_with_llm, geo_hint=geo_hint)
                for _ in range(_CORPUS_FETCH_ATTEMPTS)
            ]
            for fut in as_completed(futures):
                try:
                    chunk = fut.result()
                except LLMError:
                    continue
                corpus = _merge_corpora(corpus, chunk)
                partial_jobs = _enforce_country_priority_mix(list(corpus.get("jobs", []) or []))
                partial_df = pd.DataFrame(_job_rows_from_raw_jobs(partial_jobs))
                if on_rows is not None:
                    on_rows(partial_df)
                if len(partial_jobs) >= INTENT_CORPUS_MIN_JOBS:
                    break

    job_n = len(list(corpus.get("jobs", []) or []))
    ttl = _CORPUS_CACHE_TTL_SECONDS_OK if job_n > 0 else _CORPUS_CACHE_TTL_SECONDS_EMPTY
    _CORPUS_CACHE[key] = (now + ttl, corpus)
    jobs = _enforce_country_priority_mix(list(corpus.get("jobs", []) or []))
    return pd.DataFrame(_job_rows_from_raw_jobs(jobs))


def _enforce_country_priority_mix(jobs: list[Any]) -> list[Any]:
    """Prefer CA/US rows and rebalance toward configured CA/US split."""
    if not jobs:
        return jobs
    eligible = [j for j in jobs if isinstance(j, dict)]
    if not eligible:
        return jobs
    with_cc = sum(1 for j in eligible if str(j.get("countryCode") or "").strip())
    if with_cc < max(3, len(eligible) // 2):
        return jobs
    ca: list[dict[str, Any]] = []
    us: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for j in eligible:
        cc = str(j.get("countryCode") or "").strip().upper()
        if cc == "CA":
            ca.append(j)
        elif cc in ("US", ""):
            us.append(j)
        else:
            other.append(j)
    total = len(eligible)
    target_ca = int(round(total * CORPUS_CA_JOB_SHARE))
    target_us = int(round(total * CORPUS_US_JOB_SHARE))

    selected_ca = ca[:target_ca]
    selected_us = us[:target_us]
    out = selected_ca + selected_us
    remainder = total - len(out)

    if remainder > 0:
        extra_ca = ca[target_ca:]
        extra_us = us[target_us:]
        out.extend(extra_ca[:remainder])
        remainder = total - len(out)
        if remainder > 0:
            out.extend(extra_us[:remainder])
            remainder = total - len(out)
        if remainder > 0:
            out.extend(other[:remainder])
    return out[:total]


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
    raw_jobs = _enforce_country_priority_mix(raw_jobs)
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
                "Source": str(item.get("source") or "live_job_boards"),
            }
        )
    return pd.DataFrame(rows)
