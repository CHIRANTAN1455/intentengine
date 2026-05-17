"""HubSpot push from enriched leads (used right after the Enrichment step).

Kept separate from ``hubspot_sync`` so Streamlit / deploy caches cannot serve a
stale ``hubspot_sync.py`` that omits enrichment-only helpers while ``main.py`` is new.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from crm import seed_post_enrich_row
from enrichment import lead_has_verified_contact
from hubspot_sync import push_crm_batch


def push_enriched_dataframe_to_hubspot(
    token: str,
    df: Any,
    assigned_sdr: str,
    blacklist: set[str],
    *,
    delay_seconds: float = 0.12,
) -> dict[str, Any]:
    """
    Build CRM-shaped rows from an enriched leads dataframe and push to HubSpot.

    Only rows with a **verified** person contact (same gate as email dispatch) and
    a non-blacklisted email are synced. Duplicate emails in ``df`` are deduped
    (first row wins).
    """
    errs: list[str] = []
    out: dict[str, Any] = {
        "ok": 0,
        "skipped": 0,
        "skipped_no_qualifying": 0,
        "errors": errs,
        "source": "enrichment",
    }

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return out

    bl = {str(x).strip().lower() for x in (blacklist or [])}
    records: list[dict[str, Any]] = []
    email_to_lead: dict[str, dict[str, Any]] = {}
    seen_emails: set[str] = set()
    skipped_qual = 0

    for _, row in df.iterrows():
        if not lead_has_verified_contact(row):
            skipped_qual += 1
            continue
        em = str(row.get("Email", "") or "").strip().lower()
        if not em or em in bl:
            skipped_qual += 1
            continue
        if em in seen_emails:
            skipped_qual += 1
            continue
        seen_emails.add(em)
        email_to_lead[em] = row.to_dict()
        records.append(seed_post_enrich_row(row, assigned_sdr=assigned_sdr))

    out["skipped_no_qualifying"] = skipped_qual
    if not records:
        return out

    batch = push_crm_batch(token, records, email_to_lead, delay_seconds=delay_seconds)
    out["ok"] = batch.get("ok", 0)
    out["skipped"] = batch.get("skipped", 0)
    out["errors"] = batch.get("errors") or errs
    out["attempted"] = batch.get("attempted", 0)
    out["success"] = bool(batch.get("success"))
    out["http_status"] = batch.get("http_status")
    return out
