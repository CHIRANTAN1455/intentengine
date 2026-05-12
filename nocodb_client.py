"""NocoDB REST client for pipeline persistence."""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os
from typing import Any

import requests

from config import get_nocodb_settings


class NocoDBError(RuntimeError):
    pass


def _json_default(o: Any) -> Any:
    """JSON fallback for pandas / numpy / datetime values in the payload.

    Without this, snapshot persistence crashes the Streamlit app with
    ``TypeError: Object of type <date|bool_|int64|Timestamp|...>`` the first
    time the pipeline tries to round-trip a DataFrame-derived row.
    """
    # numpy / pandas scalars expose ``.item()`` to reach a native Python value.
    item = getattr(o, "item", None)
    if callable(item):
        try:
            v = item()
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            if isinstance(v, (_dt.date, _dt.datetime)):
                return v.isoformat()
            return v
        except Exception:
            pass

    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    if isinstance(o, _dt.timedelta):
        return o.total_seconds()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", errors="replace")

    try:
        import pandas as pd  # noqa: WPS433 — optional import; pandas is a hard dep elsewhere
        if pd.isna(o):
            return None
    except Exception:
        pass

    # Last-resort coercion — better than crashing the whole save.
    return str(o)


def _safe_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, default=_json_default)


def _payload_json_max_chars() -> int:
    """NocoDB LongText is often capped at 100k; stay safely under via env override."""
    raw = (os.environ.get("NOCODB_PAYLOAD_JSON_MAX_CHARS") or "95000").strip()
    try:
        return max(4096, min(int(raw), 999000))
    except ValueError:
        return 95000


# Fields on per-job rows that routinely blow past 100k when multiplied by corpus size.
_JOB_BLOAT_KEYS: frozenset[str] = frozenset(
    {
        "Listing snippet",
        "listingSnippet",
        "description",
        "job_description",
        "Description",
        "summary",
    }
)


def _strip_job_row_bloat(rows: list[Any] | None) -> int:
    """Remove heavy text keys from job dicts. Returns rows touched."""
    if not isinstance(rows, list):
        return 0
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in _JOB_BLOAT_KEYS:
            if k in r:
                r.pop(k, None)
                n += 1
    return n


def _truncate_row_strings(row: dict[str, Any], max_len: int) -> None:
    for k, v in list(row.items()):
        if isinstance(v, str) and len(v) > max_len:
            row[k] = v[: max_len - 1] + "…"


def _truncate_list_rows_strings(rows: list[Any], max_len: int) -> None:
    for r in rows:
        if isinstance(r, dict):
            _truncate_row_strings(r, max_len)


def _crm_like_lists(payload: dict[str, Any]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for key in ("crm_records", "records"):
        v = payload.get(key)
        if isinstance(v, list):
            out.append(v)
    return out


def _shrink_payload_for_longtext(payload: dict[str, Any], meta: dict[str, Any], step: int) -> None:
    """Single compaction step (``step`` index). Mutates ``payload`` in place."""
    if step == 0:
        body = payload.get("body")
        if isinstance(body, str) and len(body) > 45000:
            payload["body"] = body[:44999] + "…"
            meta["event_body_trimmed"] = True
        jobs = payload.get("company_jobs")
        if _strip_job_row_bloat(jobs):
            meta["job_listing_text_removed"] = True
    elif step == 1:
        for lst in _crm_like_lists(payload):
            for r in lst:
                if isinstance(r, dict) and isinstance(r.get("interaction_history"), str):
                    h = r["interaction_history"]
                    if len(h) > 8000:
                        r["interaction_history"] = h[:7999] + "…"
                        meta["crm_history_trimmed"] = True
    elif step == 2:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list):
            _truncate_list_rows_strings(jobs, 900)
            meta["job_strings_truncated_900"] = True
    elif step == 3:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list) and len(jobs) > 450:
            payload["company_jobs"] = jobs[:450]
            meta["company_jobs_capped_450"] = True
    elif step == 4:
        for lst in _crm_like_lists(payload):
            for r in lst:
                if isinstance(r, dict):
                    _truncate_row_strings(r, 3500)
    elif step == 5:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list):
            _truncate_list_rows_strings(jobs, 400)
    elif step == 6:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list) and len(jobs) > 200:
            payload["company_jobs"] = jobs[:200]
            meta["company_jobs_capped_200"] = True
    elif step == 7:
        si = payload.get("social_intent")
        if isinstance(si, list) and len(si) > 250:
            payload["social_intent"] = si[:250]
            meta["social_intent_capped"] = True
        rs = payload.get("role_suggestions")
        if isinstance(rs, list) and len(rs) > 400:
            payload["role_suggestions"] = rs[:400]
            meta["role_suggestions_capped"] = True
    elif step == 8:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list) and len(jobs) > 80:
            payload["company_jobs"] = jobs[:80]
            meta["company_jobs_capped_80"] = True
    elif step == 9:
        if payload.get("company_jobs") is not None:
            payload["company_jobs"] = None
            meta["company_jobs_dropped"] = True
    elif step == 10:
        le = payload.get("leads_enriched")
        if isinstance(le, list) and len(le) > 500:
            payload["leads_enriched"] = le[:500]
            meta["leads_enriched_capped"] = True
    elif step == 11:
        for key in ("crm_records", "records"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 250:
                payload[key] = v[:250]
                meta[f"{key}_capped_250"] = True
    elif step == 12:
        for key in ("company_scored", "_ready_for_enrich"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 800:
                payload[key] = v[:800]
                meta[f"{key}_capped_800"] = True
    elif step == 13:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list):
            for r in jobs:
                if isinstance(r, dict):
                    for uk in ("Job URL", "job_url", "url", "Job URLs (sample)"):
                        u = r.get(uk)
                        if isinstance(u, str) and len(u) > 600:
                            r[uk] = u[:599] + "…"
            meta["job_urls_truncated"] = True
    elif step == 14:
        for key in ("company_scored", "_ready_for_enrich"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 400:
                payload[key] = v[:400]
                meta[f"{key}_capped_400"] = True
    elif step == 15:
        for key in ("company_scored", "_ready_for_enrich"):
            rows = payload.get(key)
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and isinstance(r.get("Intent reason"), str):
                        ir = r["Intent reason"]
                        if len(ir) > 400:
                            r["Intent reason"] = ir[:399] + "…"
        meta["intent_reason_trimmed"] = True
    elif step == 16:
        rep = payload.get("replies")
        if isinstance(rep, list) and len(rep) > 80:
            payload["replies"] = rep[:80]
            meta["replies_capped"] = True
    elif step == 17:
        for key in ("company_scored", "_ready_for_enrich"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 200:
                payload[key] = v[:200]
                meta[f"{key}_capped_200b"] = True
    elif step == 18:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list):
            _truncate_list_rows_strings(jobs, 220)
    elif step == 19:
        bl = payload.get("blacklist")
        if isinstance(bl, list) and len(bl) > 2000:
            payload["blacklist"] = bl[:2000]
            meta["blacklist_capped"] = True
    elif step == 20:
        for key in ("company_scored", "_ready_for_enrich"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 120:
                payload[key] = v[:120]
                meta[f"{key}_capped_120"] = True
    elif step == 21:
        jobs = payload.get("company_jobs")
        if isinstance(jobs, list):
            _truncate_list_rows_strings(jobs, 120)
    elif step == 22:
        for key in ("company_scored", "_ready_for_enrich", "leads_enriched"):
            v = payload.get(key)
            if isinstance(v, list) and len(v) > 80:
                payload[key] = v[:80]
                meta[f"{key}_capped_80b"] = True
    elif step == 23:
        payload["_ready_for_enrich"] = None
        meta["_ready_for_enrich_nulled"] = True
        cs = payload.get("company_scored")
        if isinstance(cs, list) and len(cs) > 60:
            payload["company_scored"] = cs[:60]
            meta["company_scored_capped_60"] = True
    elif step == 24:
        b = payload.get("body")
        if isinstance(b, str) and len(b) > 12000:
            payload["body"] = b[:11999] + "…"
            meta["top_level_body_trimmed"] = True


def _dumps_under_longtext_limit(payload: dict[str, Any]) -> str:
    """Serialize for NocoDB LongText (~100k). Progressively drops job snippets / caps lists."""
    max_c = _payload_json_max_chars()
    slim: dict[str, Any] = copy.deepcopy(payload)
    meta_acc: dict[str, Any] = {}
    for step in range(30):
        blob = _safe_dumps(slim)
        if len(blob) <= max_c:
            if meta_acc:
                slim["_nocodb_compact"] = dict(meta_acc)
                blob2 = _safe_dumps(slim)
                if len(blob2) <= max_c:
                    return blob2
                slim.pop("_nocodb_compact", None)
            return blob
        _shrink_payload_for_longtext(slim, meta_acc, step)
    blob = _safe_dumps(slim)
    raise NocoDBError(
        f"Snapshot JSON still {len(blob)} chars after compaction; NocoDB LongText limit is ~{max_c}. "
        "Increase NOCODB_PAYLOAD_JSON_MAX_CHARS only if the column type allows it, or use a larger text column in NocoDB."
    )


def _headers() -> dict[str, str]:
    s = get_nocodb_settings()
    return {
        "xc-token": s.api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _table_url(table_id: str) -> str:
    s = get_nocodb_settings()
    return f"{s.base_url.rstrip('/')}/api/v2/tables/{table_id}/records"


def _extract_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in ("list", "records", "data", "items"):
        val = body.get(key)
        if isinstance(val, list):
            return val
    return []


def list_records(table_id: str, limit: int = 200) -> list[dict[str, Any]]:
    url = _table_url(table_id)
    response = requests.get(url, headers=_headers(), params={"limit": limit}, timeout=30)
    if response.status_code >= 400:
        raise NocoDBError(f"NocoDB list failed ({response.status_code}): {response.text[:300]}")
    return _extract_list(response.json())


def _record_id(row: dict[str, Any]) -> str:
    return str(row.get("Id") or row.get("id") or row.get("recordId") or "").strip()


def find_snapshot_by_session(session_id: str) -> tuple[str | None, dict[str, Any] | None]:
    s = get_nocodb_settings()
    session_field = s.field_session_id
    for row in list_records(s.table_id):
        sid = str(row.get(session_field) or row.get("Session_id") or row.get("session_id") or "").strip()
        if sid == session_id:
            return _record_id(row) or None, row
    return None, None


def upsert_snapshot(session_id: str, step: int, payload: dict[str, Any]) -> str:
    """Create or update snapshot row; returns record id."""
    s = get_nocodb_settings()
    rid, _existing = find_snapshot_by_session(session_id)
    url = _table_url(s.table_id)
    body = {
        s.field_session_id: session_id,
        s.field_step: step,
        s.field_payload_json: _dumps_under_longtext_limit(payload),
    }
    if rid:
        patch_url = f"{url}/{rid}"
        response = requests.patch(patch_url, headers=_headers(), json=body, timeout=30)
        if response.status_code >= 400:
            raise NocoDBError(f"NocoDB patch failed ({response.status_code}): {response.text[:300]}")
        return rid

    response = requests.post(url, headers=_headers(), json=body, timeout=30)
    if response.status_code >= 400:
        raise NocoDBError(f"NocoDB create failed ({response.status_code}): {response.text[:300]}")
    data = response.json()
    new_id = _record_id(data) or _record_id(data.get("record", {}) if isinstance(data, dict) else {})
    if not new_id:
        raise NocoDBError("NocoDB create did not return record id.")
    return new_id


def append_event(event_type: str, payload: dict[str, Any]) -> None:
    """Append an audit row (optional second table)."""
    s = get_nocodb_settings()
    if not s.events_table_id:
        return
    url = _table_url(s.events_table_id)
    body = {
        s.field_event_type: event_type,
        s.field_event_payload_json: _dumps_under_longtext_limit(payload),
    }
    response = requests.post(url, headers=_headers(), json=body, timeout=30)
    if response.status_code >= 400:
        raise NocoDBError(f"NocoDB event log failed ({response.status_code}): {response.text[:300]}")
