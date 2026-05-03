"""In-house intent ingestion powered by OpenRouter structured generation."""

from __future__ import annotations

from datetime import date, timedelta
import time
import pandas as pd

from config import SALES_ROLE_KEYWORDS
from openrouter_client import OpenRouterError, generate_intent_corpus_with_openrouter

_CORPUS_CACHE: dict[str, object] | None = None
_CORPUS_EXPIRES_AT = 0.0


def invalidate_intent_corpus_cache() -> None:
    global _CORPUS_CACHE, _CORPUS_EXPIRES_AT
    _CORPUS_CACHE = None
    _CORPUS_EXPIRES_AT = 0.0


def _get_corpus() -> dict:
    global _CORPUS_CACHE, _CORPUS_EXPIRES_AT
    now = time.time()
    if _CORPUS_CACHE and now < _CORPUS_EXPIRES_AT:
        return _CORPUS_CACHE  # type: ignore[return-value]
    try:
        corpus = generate_intent_corpus_with_openrouter()
    except OpenRouterError:
        corpus = {"jobs": [], "social": []}
    _CORPUS_CACHE = corpus
    _CORPUS_EXPIRES_AT = now + 15 * 60
    return corpus


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


def fetch_job_postings() -> pd.DataFrame:
    corpus = _get_corpus()
    rows: list[dict] = []
    for item in corpus.get("jobs", []) or []:
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
            }
        )
    return pd.DataFrame(rows)


def fetch_social_intent() -> pd.DataFrame:
    corpus = _get_corpus()
    rows: list[dict] = []
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
