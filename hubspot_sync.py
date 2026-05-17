"""
Push IntentEngine CRM rows to HubSpot as contacts + a timeline note.

Uses the private app / OAuth access token (``HUBSPOT_ACCESS_TOKEN`` or
``HUBSPOT_PRIVATE_APP_TOKEN``). Contacts are upserted by email; job/intent
context is stored in a note on the contact record.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

HUBSPOT_API = "https://api.hubapi.com"
# Note → contact (HubSpot-defined); see CRM Notes associations.
NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID = 202
REQUEST_TIMEOUT = 45


def _escape_note_text(s: str) -> str:
    return html.escape(s, quote=True).replace("\n", "<br/>")


def _split_name(full: str) -> tuple[str, str]:
    full = (full or "").strip()
    if not full:
        return "", ""
    parts = full.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _clean_props(props: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in props.items() if v is not None and str(v).strip() != ""}


def search_contact_id_by_email(token: str, email: str) -> str | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    url = f"{HUBSPOT_API}/crm/v3/objects/contacts/search"
    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": email,
                    }
                ]
            }
        ],
        "properties": ["email"],
        "limit": 1,
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HubSpot contact search failed ({r.status_code}): {r.text[:500]}")
    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    rid = results[0].get("id")
    return str(rid) if rid is not None else None


def _create_contact(token: str, properties: dict[str, str]) -> str:
    url = f"{HUBSPOT_API}/crm/v3/objects/contacts"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"properties": properties},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"HubSpot create contact failed ({r.status_code}): {r.text[:800]}")
    data = r.json()
    cid = data.get("id")
    if not cid:
        raise RuntimeError("HubSpot create contact returned no id")
    return str(cid)


def _create_contact_resilient(token: str, properties: dict[str, str]) -> str:
    try:
        return _create_contact(token, properties)
    except RuntimeError as exc:
        msg = str(exc)
        if "hs_linkedin_url" in msg or "PROPERTY_DOESNT_EXIST" in msg or "INVALID_OPTION" in msg:
            stripped = {k: v for k, v in properties.items() if k != "hs_linkedin_url"}
            return _create_contact(token, stripped)
        raise


def _patch_contact(token: str, contact_id: str, properties: dict[str, str]) -> None:
    url = f"{HUBSPOT_API}/crm/v3/objects/contacts/{contact_id}"
    r = requests.patch(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"properties": properties},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HubSpot update contact failed ({r.status_code}): {r.text[:800]}")


def _patch_contact_resilient(token: str, contact_id: str, properties: dict[str, str]) -> None:
    try:
        _patch_contact(token, contact_id, properties)
    except RuntimeError as exc:
        msg = str(exc)
        if "hs_linkedin_url" in msg or "PROPERTY_DOESNT_EXIST" in msg or "INVALID_OPTION" in msg:
            stripped = {k: v for k, v in properties.items() if k != "hs_linkedin_url"}
            if stripped:
                _patch_contact(token, contact_id, stripped)
            return
        raise


def _create_note_on_contact(token: str, contact_id: str, body_text: str) -> None:
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    body_html = f"<p>{_escape_note_text(body_text)}</p>"
    url = f"{HUBSPOT_API}/crm/v3/objects/notes"
    payload = {
        "properties": {
            "hs_timestamp": str(ts_ms),
            "hs_note_body": body_html,
        },
        "associations": [
            {
                "to": {"id": str(contact_id)},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID,
                    }
                ],
            }
        ],
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"HubSpot create note failed ({r.status_code}): {r.text[:800]}")


def _build_note_body(crm: dict[str, Any], lead: dict[str, Any] | None) -> str:
    lines: list[str] = []
    lines.append("— IntentEngine / hirequity —")
    co = str(crm.get("company") or "").strip()
    if co:
        lines.append(f"Company: {co}")
    role = str(crm.get("hiring_role") or "").strip()
    if role:
        lines.append(f"Hiring role (posting): {role}")
    ir = str(crm.get("intent_reason") or "").strip()
    if ir:
        lines.append(f"Intent / signals: {ir}")
    try:
        score = float(crm.get("intent_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    tier = str(crm.get("intent_tier") or "").strip()
    lines.append(f"Intent score: {score:g}" + (f" · Tier: {tier}" if tier else ""))
    st = str(crm.get("lead_status") or "").strip()
    if st:
        lines.append(f"Pipeline status: {st}")
    if lead:
        ju = str(lead.get("Job URLs") or lead.get("Job URL") or "").strip()
        if ju:
            lines.append(f"Job link(s): {ju}")
        snip = str(lead.get("Listing snippet") or "").strip()
        if snip:
            snip = re.sub(r"\s+", " ", snip)
            if len(snip) > 1200:
                snip = snip[:1197] + "…"
            lines.append(f"Posting excerpt: {snip}")
        pd = str(lead.get("Posting date") or "").strip()
        if pd:
            lines.append(f"Posting date: {pd}")
    hist = str(crm.get("interaction_history") or "").strip()
    if hist:
        tail = hist[-1500:] if len(hist) > 1500 else hist
        lines.append(f"Interaction log (recent): {tail}")
    return "\n".join(lines)


def _contact_properties(
    crm: dict[str, Any],
    first: str,
    last: str,
    email: str,
) -> dict[str, str]:
    phone = str(crm.get("phone") or "").strip()
    company = str(crm.get("company") or "").strip()
    li = str(crm.get("linkedin") or "").strip()
    hiring = str(crm.get("hiring_role") or "").strip()
    props: dict[str, str] = {
        "email": email,
        "firstname": first,
        "lastname": last or first or "Unknown",
        "company": company,
        "phone": phone,
        "jobtitle": hiring[:255] if hiring else "",
    }
    if li:
        # Standard on most Sales/Marketing portals; omitted if empty.
        props["hs_linkedin_url"] = li
    return _clean_props(props)


def upsert_contact_with_note(
    token: str,
    crm_record: dict[str, Any],
    lead_row: dict[str, Any] | None,
) -> tuple[str, bool]:
    """
    Upsert HubSpot contact by email and attach a note with job + intent context.

    Returns ``(hubspot_contact_id, created)`` where ``created`` is True when a
    new contact row was created rather than updated.
    """
    email = str(crm_record.get("email") or "").strip().lower()
    if not email:
        raise ValueError("CRM row has no email — HubSpot contact requires an email.")

    full_name = str(crm_record.get("name") or "").strip()
    first, last = _split_name(full_name)
    props = _contact_properties(crm_record, first, last, email)

    existing = search_contact_id_by_email(token, email)
    note_body = _build_note_body(crm_record, lead_row)

    if existing:
        # Do not send blank strings that could clear HubSpot fields unintentionally.
        patch = {k: v for k, v in props.items() if k != "email" and v}
        if patch:
            _patch_contact_resilient(token, existing, patch)
        try:
            _create_note_on_contact(token, existing, note_body)
        except RuntimeError as exc:
            raise RuntimeError(f"Contact {existing} updated but note failed: {exc}") from exc
        return existing, False

    cid = _create_contact_resilient(token, props)
    try:
        _create_note_on_contact(token, cid, note_body)
    except RuntimeError as exc:
        raise RuntimeError(f"Contact {cid} created but note failed: {exc}") from exc
    return cid, True


def push_crm_batch(
    token: str,
    crm_records: list[dict[str, Any]],
    email_to_lead: dict[str, dict[str, Any]],
    *,
    delay_seconds: float = 0.12,
) -> dict[str, Any]:
    """
    Push each CRM record that has an email. ``email_to_lead`` maps lowercase
    email to an optional enriched-lead dict (for job URLs / posting text).
    """
    errs: list[str] = []
    summary: dict[str, Any] = {
        "ok": 0,
        "skipped": 0,
        "errors": errs,
        "attempted": 0,
        "success": False,
        "http_status": None,
    }
    for rec in crm_records:
        if not isinstance(rec, dict):
            continue
        em = str(rec.get("email") or "").strip().lower()
        if not em:
            summary["skipped"] += 1
            continue
        lead = email_to_lead.get(em)
        summary["attempted"] += 1
        try:
            cid, created = upsert_contact_with_note(token, rec, lead)
            summary["ok"] += 1
            log = (
                f"{datetime.now(timezone.utc).isoformat()}Z — "
                f"HubSpot: {'created' if created else 'updated'} contact id {cid}"
            )
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (prev + " | " + log).strip(" |")
        except Exception as exc:  # noqa: BLE001 — surface to UI
            errs.append(f"{em}: {exc}")
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    if summary["ok"] > 0 and not errs:
        summary["success"] = True
        summary["http_status"] = 200
    return summary
