"""Apollo.io contact enrichment (real people + work emails).

Also exposes :data:`LAST_APOLLO_ERROR` so the Streamlit UI can show the
first HTTP/connection error seen on the most recent enrichment run, plus
:func:`apollo_quick_probe` for a sidebar “Test Apollo key” button.


This replaces the earlier “LLM-invented contact” path: every surfaced email /
name / phone / LinkedIn profile here comes from Apollo’s database + their
``people/match`` reveal flow (consumes Apollo credits per your plan).

**Why this was missing before:** production safety required dropping fabricated
contacts; no third-party API had been integrated yet.

**Phones:** Apollo returns synchronous phone data only when present on the
record. Full ``reveal_phone_number`` delivery often requires a public
``webhook_url`` — set ``APOLLO_PHONE_WEBHOOK_URL`` if you need async mobile
reveal; otherwise we still show any phone Apollo returns inline.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

import requests

from config import (
    apollo_api_key,
    apollo_phone_webhook_url,
    enrichment_max_companies_per_run,
    enrichment_request_delay_seconds,
)

_APOLLO_BASE = "https://api.apollo.io/api/v1"

# Last error seen during an Apollo call on this Python process (debug aid).
LAST_APOLLO_ERROR: str = ""


def _set_last_error(msg: str) -> None:
    global LAST_APOLLO_ERROR
    LAST_APOLLO_ERROR = msg


def apollo_last_error() -> str:
    return LAST_APOLLO_ERROR


def apollo_quick_probe() -> tuple[bool, str]:
    """Single low-cost POST to confirm the key works. Returns (ok, message)."""
    if not apollo_contact_enrichment_available():
        return False, "APOLLO_API_KEY is not set in env or Streamlit secrets."
    try:
        r = requests.post(
            f"{_APOLLO_BASE}/mixed_people/api_search",
            headers=_headers(),
            json={"q_organization_name": "Apollo", "page": 1, "per_page": 1},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    if r.status_code in (401, 403):
        return False, f"HTTP {r.status_code}: key rejected. Use a master API key (Apollo → Settings → API)."
    if r.status_code == 422:
        return False, f"HTTP 422 from Apollo: {r.text[:240]}"
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}: {r.text[:240]}"
    try:
        body = r.json()
    except ValueError:
        return False, "Apollo returned non-JSON response."
    people = body.get("people")
    if isinstance(people, list):
        return True, f"OK — Apollo responded with {len(people)} sample row(s)."
    return True, "OK — Apollo responded (no rows for probe query)."


_SALES_TITLE_HINTS = (
    "sales",
    "revenue",
    "commercial",
    "account executive",
    "business development",
    "sdr",
    "bdr",
    "cro",
    "gtm",
    "go-to-market",
    "enterprise",
    "channel sales",
)


def apollo_contact_enrichment_available() -> bool:
    return bool(apollo_api_key())


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": apollo_api_key(),
    }


def _title_filters(hiring_role_hint: str | None) -> list[str]:
    base = [
        "sales director",
        "vp sales",
        "vice president sales",
        "head of sales",
        "chief revenue officer",
        "cro",
        "sales manager",
        "account executive",
        "sales development representative",
        "business development representative",
    ]
    if hiring_role_hint:
        first = hiring_role_hint.split(";")[0].strip()
        if first and len(first) > 2:
            base = [first[:120]] + [t for t in base if t.lower() != first.lower()]
    return base[:10]


def _org_matches(company: str, person: dict[str, Any]) -> bool:
    org = person.get("organization") or {}
    oname = str(org.get("name") or "").strip().lower()
    c = company.strip().lower()
    if not oname or not c:
        return True
    return c in oname or oname in c


def _score_person(company: str, person: dict[str, Any]) -> float:
    title = str(person.get("title") or "").lower()
    score = 0.0
    if person.get("has_email"):
        score += 4.0
    if _org_matches(company, person):
        score += 3.0
    for kw in _SALES_TITLE_HINTS:
        if kw in title:
            score += 1.2
    return score


def _pick_best_person(company: str, people: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_s = -1.0
    for p in people:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        s = _score_person(company, p)
        if s > best_s:
            best_s = s
            best = p
    return best


def _extract_phone(person: dict[str, Any]) -> str:
    for k in ("direct_phone", "sanitized_phone", "mobile_phone"):
        v = person.get(k)
        if isinstance(v, str) and re.sub(r"\D", "", v):
            return v.strip()
    nums = person.get("phone_numbers")
    if isinstance(nums, list):
        for item in nums:
            if not isinstance(item, dict):
                continue
            for sk in ("sanitized_number", "raw_number", "number"):
                raw = item.get(sk)
                if isinstance(raw, str) and re.sub(r"\D", "", raw):
                    return raw.strip()
    org = person.get("organization") or {}
    if isinstance(org, dict):
        op = org.get("primary_phone") or org.get("phone")
        if isinstance(op, str) and re.sub(r"\D", "", op):
            return op.strip()
    return ""


def fetch_apollo_contact_for_company(
    company: str,
    hiring_role_hint: str | None,
    *,
    timeout: int = 28,
) -> dict[str, Any] | None:
    """Return a flat dict of contact fields, or ``None`` if no Apollo hit.

    Keys on success: ``name``, ``title``, ``email``, ``phone``, ``linkedin``,
    ``provider``, ``apollo_person_id``.
    """
    if not apollo_contact_enrichment_available():
        return None
    titles = _title_filters(hiring_role_hint)
    body: dict[str, Any] = {
        "q_organization_name": company.strip(),
        "person_titles": titles,
        "page": 1,
        "per_page": 15,
    }
    try:
        r = requests.post(
            f"{_APOLLO_BASE}/mixed_people/api_search",
            headers=_headers(),
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _set_last_error(f"search network error: {exc}")
        return None
    if r.status_code >= 400:
        _set_last_error(f"search HTTP {r.status_code}: {r.text[:200]}")
        return None
    try:
        data = r.json()
    except ValueError:
        _set_last_error("search response was not JSON")
        return None
    people = data.get("people")
    if not isinstance(people, list) or not people:
        return None
    pick = _pick_best_person(company, people)
    if not pick:
        return None
    pid = str(pick.get("id") or "").strip()
    if not pid:
        return None

    params: dict[str, Any] = {
        "id": pid,
        "reveal_personal_emails": "true",
    }
    wh = apollo_phone_webhook_url()
    if wh:
        params["reveal_phone_number"] = "true"
        params["webhook_url"] = wh

    try:
        r2 = requests.post(
            f"{_APOLLO_BASE}/people/match",
            headers=_headers(),
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _set_last_error(f"match network error: {exc}")
        return None
    if r2.status_code >= 400:
        _set_last_error(f"match HTTP {r2.status_code}: {r2.text[:200]}")
        return None
    try:
        mdata = r2.json()
    except ValueError:
        _set_last_error("match response was not JSON")
        return None
    person = mdata.get("person")
    if not isinstance(person, dict):
        return None
    email = str(person.get("email") or "").strip()
    if not email:
        return None
    first = str(person.get("first_name") or "").strip()
    last = str(person.get("last_name") or "").strip()
    name = str(person.get("name") or "").strip() or " ".join(x for x in (first, last) if x).strip()
    title = str(person.get("title") or "").strip()
    phone = _extract_phone(person)
    li = str(person.get("linkedin_url") or "").strip()
    return {
        "name": name,
        "title": title,
        "email": email,
        "phone": phone,
        "linkedin": li,
        "provider": "apollo",
        "apollo_person_id": pid,
    }


def run_apollo_waterfall_on_dataframe(
    df_rows: list[dict[str, Any]],
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Augment in-memory enrichment row dicts with Apollo contacts (bounded batch)."""
    if not apollo_contact_enrichment_available():
        return df_rows
    _set_last_error("")
    delay = enrichment_request_delay_seconds()
    cap = enrichment_max_companies_per_run()
    total = min(len(df_rows), cap)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(df_rows):
        if i >= cap:
            out.append(row)
            continue
        if on_progress:
            on_progress(i + 1, total, str(row.get("Company") or ""))
        contact = fetch_apollo_contact_for_company(
            str(row.get("Company") or ""),
            str(row.get("Hiring role") or row.get("Title") or "") or None,
        )
        merged = dict(row)
        if contact:
            merged["Name"] = contact["name"]
            merged["Title"] = contact["title"] or merged.get("Title", "")
            merged["Email"] = contact["email"]
            merged["Phone"] = contact["phone"]
            if contact.get("linkedin"):
                merged["LinkedIn"] = contact["linkedin"]
            merged["Enrichment verified"] = True
            merged["Contact source"] = "apollo"
            merged["Contact status"] = "Verified (Apollo)"
        else:
            merged.setdefault("Contact source", "")
        out.append(merged)
        if delay > 0 and i < min(len(df_rows), cap) - 1:
            time.sleep(delay)
    return out
