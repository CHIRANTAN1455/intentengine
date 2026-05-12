"""NocoDB REST client for pipeline persistence."""

from __future__ import annotations

import json
from typing import Any

import requests

from config import get_nocodb_settings


class NocoDBError(RuntimeError):
    pass


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
        s.field_payload_json: json.dumps(payload, ensure_ascii=True),
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
        s.field_event_payload_json: json.dumps(payload, ensure_ascii=True),
    }
    response = requests.post(url, headers=_headers(), json=body, timeout=30)
    if response.status_code >= 400:
        raise NocoDBError(f"NocoDB event log failed ({response.status_code}): {response.text[:300]}")
