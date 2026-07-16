"""SmartLead cold-email outreach (campaign enroll + sequence sync).

MailerSend rejected cold outreach; SmartLead is the outbound provider.
API: https://server.smartlead.ai/api/v1  (auth via ``?api_key=``).

Dispatch model: enroll leads into a campaign. Per-lead IntentEngine
subject/body copy is stored in custom fields ``ie_subject_N`` / ``ie_body_N``
and campaign sequences merge those tags.
"""
from __future__ import annotations

import html
import re
from typing import Any

import requests

from config import (
    smartlead_api_key,
    smartlead_campaign_id,
    smartlead_campaign_name,
)

_SMARTLEAD_API = "https://server.smartlead.ai/api/v1"
_REQUEST_TIMEOUT = 45
_DEFAULT_CAMPAIGN_NAME = "IntentEngine Outreach"

LAST_SMARTLEAD_ERROR: str = ""


def _set_last_error(msg: str) -> None:
    global LAST_SMARTLEAD_ERROR
    LAST_SMARTLEAD_ERROR = msg


def smartlead_last_error() -> str:
    return LAST_SMARTLEAD_ERROR


def _params() -> dict[str, str]:
    return {"api_key": smartlead_api_key()}


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _extract_error(response: requests.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:400]
    if isinstance(body, dict):
        for key in ("message", "error", "msg"):
            if body.get(key):
                return str(body[key])[:400]
    return response.text[:400]


def _plain_to_html(text: str) -> str:
    escaped = html.escape(text or "")
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br/>") + "</p>"


def _split_name(full: str) -> tuple[str, str]:
    full = (full or "").strip()
    if not full:
        return "", ""
    parts = full.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _request(
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    timeout: int = _REQUEST_TIMEOUT,
) -> tuple[bool, Any, str]:
    if not smartlead_api_key():
        return False, None, "SMARTLEAD_API_KEY is not set."
    url = f"{_SMARTLEAD_API}{path}"
    try:
        r = requests.request(
            method,
            url,
            params=_params(),
            headers=_headers(),
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _set_last_error(str(exc))
        return False, None, f"Network error: {exc}"

    if r.status_code in (401, 403):
        msg = f"HTTP {r.status_code}: SmartLead API key rejected."
        _set_last_error(msg)
        return False, None, msg
    if r.status_code >= 400:
        msg = f"HTTP {r.status_code}: {_extract_error(r)}"
        _set_last_error(msg)
        return False, None, msg

    if not r.content:
        return True, None, ""
    try:
        return True, r.json(), ""
    except ValueError:
        return True, r.text, ""


def list_campaigns() -> tuple[bool, list[dict[str, Any]], str]:
    ok, body, err = _request("GET", "/campaigns/")
    if not ok:
        return False, [], err
    if isinstance(body, list):
        return True, [c for c in body if isinstance(c, dict)], ""
    if isinstance(body, dict):
        data = body.get("data") or body.get("campaigns") or []
        if isinstance(data, list):
            return True, [c for c in data if isinstance(c, dict)], ""
    return True, [], ""


def list_email_accounts() -> tuple[bool, list[dict[str, Any]], str]:
    ok, body, err = _request("GET", "/email-accounts/", timeout=30)
    if not ok:
        return False, [], err
    if isinstance(body, list):
        return True, [a for a in body if isinstance(a, dict)], ""
    return True, [], ""


def smartlead_quick_probe() -> tuple[bool, str]:
    """Confirm API key + summarize campaigns / sender accounts (no lead enrolled)."""
    if not smartlead_api_key():
        return False, "SMARTLEAD_API_KEY is not set in env or Streamlit secrets."

    ok_c, campaigns, err_c = list_campaigns()
    if not ok_c:
        return False, err_c

    ok_a, accounts, err_a = list_email_accounts()
    senders: list[str] = []
    if ok_a:
        for a in accounts:
            em = str(a.get("from_email") or a.get("username") or "").strip()
            if em:
                senders.append(em)

    cid = resolve_campaign_id(create_if_missing=False)
    bits = [f"OK — {len(campaigns)} campaign(s)"]
    if cid:
        bits.append(f"campaign_id={cid}")
    if senders:
        bits.append(f"sender(s): {', '.join(senders[:3])}")
    elif err_a:
        bits.append(f"email accounts: {err_a}")
    else:
        bits.append("no email accounts connected yet — add one in SmartLead")
    _set_last_error("")
    return True, " · ".join(bits)


def create_campaign(name: str | None = None) -> tuple[bool, int | None, str]:
    payload = {"name": (name or smartlead_campaign_name() or _DEFAULT_CAMPAIGN_NAME).strip()}
    ok, body, err = _request("POST", "/campaigns/create", json_body=payload)
    if not ok:
        return False, None, err
    if isinstance(body, dict):
        cid = body.get("id")
        if cid is None and isinstance(body.get("data"), dict):
            cid = body["data"].get("id")
        if cid is not None:
            return True, int(cid), f"Created campaign {cid}."
    return False, None, "Campaign create returned no id."


def resolve_campaign_id(*, create_if_missing: bool = True) -> int | None:
    raw = smartlead_campaign_id()
    if raw:
        try:
            return int(str(raw).strip())
        except ValueError:
            pass

    ok, campaigns, _ = list_campaigns()
    if ok and campaigns:
        wanted = (smartlead_campaign_name() or _DEFAULT_CAMPAIGN_NAME).strip().lower()
        for c in campaigns:
            if str(c.get("name") or "").strip().lower() == wanted:
                try:
                    return int(c["id"])
                except (KeyError, TypeError, ValueError):
                    continue
        try:
            return int(campaigns[0]["id"])
        except (KeyError, TypeError, ValueError):
            pass

    if not create_if_missing:
        return None
    ok, cid, _ = create_campaign()
    return cid if ok else None


def _ensure_email_account_on_campaign(campaign_id: int) -> tuple[bool, str]:
    ok, accounts, err = list_email_accounts()
    if not ok:
        return False, err
    if not accounts:
        return False, "No SmartLead email accounts found. Connect a sender in app.smartlead.ai first."

    # Prefer SMTP-success accounts; fall back to first.
    ready = [a for a in accounts if a.get("is_smtp_success") is True] or accounts
    account_id = ready[0].get("id")
    if account_id is None:
        return False, "SmartLead email account is missing an id."

    ok_list, existing, _ = _request("GET", f"/campaigns/{campaign_id}/email-accounts")
    existing_ids: set[int] = set()
    if ok_list and isinstance(existing, list):
        for row in existing:
            if isinstance(row, dict):
                eid = row.get("email_account_id") or row.get("id")
                try:
                    existing_ids.add(int(eid))
                except (TypeError, ValueError):
                    pass
        # Some responses nest account under email_account
        for row in existing:
            if isinstance(row, dict) and isinstance(row.get("email_account"), dict):
                try:
                    existing_ids.add(int(row["email_account"]["id"]))
                except (KeyError, TypeError, ValueError):
                    pass

    if int(account_id) in existing_ids:
        return True, f"Sender already on campaign ({ready[0].get('from_email') or account_id})."

    ok_add, _, err_add = _request(
        "POST",
        f"/campaigns/{campaign_id}/email-accounts",
        json_body={"email_account_ids": [int(account_id)]},
    )
    if not ok_add:
        return False, err_add
    return True, f"Linked sender {ready[0].get('from_email') or account_id}."


def sync_campaign_sequences(campaign_id: int, steps: int = 3) -> tuple[bool, str]:
    """Point campaign steps at IntentEngine custom-field merge tags."""
    steps = max(1, min(int(steps), 5))
    sequences: list[dict[str, Any]] = []
    delays = [0, 2, 3, 4, 5]
    for i in range(1, steps + 1):
        sequences.append(
            {
                "seq_number": i,
                "subject": f"{{{{ie_subject_{i}}}}}",
                "email_body": f"<div>{{{{ie_body_{i}}}}}</div>",
                "seq_delay_details": {"delay_in_days": delays[i - 1] if i - 1 < len(delays) else i},
            }
        )
    ok, _, err = _request(
        "POST",
        f"/campaigns/{campaign_id}/sequences",
        json_body={"sequences": sequences},
    )
    if not ok:
        return False, err
    return True, f"Synced {steps} sequence step(s)."


def ensure_campaign_schedule(campaign_id: int) -> tuple[bool, str]:
    payload = {
        "timezone": "America/New_York",
        "days_of_the_week": [1, 2, 3, 4, 5],
        "start_hour": "09:00",
        "end_hour": "17:00",
        "min_time_btw_emails": 10,
        "max_new_leads_per_day": 30,
    }
    ok, _, err = _request("POST", f"/campaigns/{campaign_id}/schedule", json_body=payload)
    if ok:
        return True, "Schedule configured."
    nested = {
        "timezone": "America/New_York",
        "days_of_the_week": [1, 2, 3, 4, 5],
        "start_hour": "09:00",
        "end_hour": "17:00",
        "min_time_btw_emails": 10,
    }
    ok2, _, err2 = _request("POST", f"/campaigns/{campaign_id}/schedule", json_body=nested)
    if not ok2:
        return False, err or err2
    return True, "Schedule configured."


def start_campaign(campaign_id: int) -> tuple[bool, str]:
    ok, body, err = _request(
        "POST",
        f"/campaigns/{campaign_id}/status",
        json_body={"status": "START"},
    )
    if ok:
        return True, "Campaign START requested."
    # Already running is fine
    if err and re.search(r"already|started|active", err, re.I):
        return True, err
    return False, err


def ensure_campaign_ready(steps: int = 3) -> tuple[bool, int | None, str]:
    """Resolve campaign, link sender, sync sequences, schedule, attempt START."""
    cid = resolve_campaign_id(create_if_missing=True)
    if not cid:
        return False, None, "Could not resolve or create a SmartLead campaign."

    notes: list[str] = [f"campaign_id={cid}"]
    ok_acc, msg_acc = _ensure_email_account_on_campaign(cid)
    if not ok_acc:
        return False, cid, msg_acc
    notes.append(msg_acc)

    ok_seq, msg_seq = sync_campaign_sequences(cid, steps=steps)
    if not ok_seq:
        return False, cid, msg_seq
    notes.append(msg_seq)

    ok_sch, msg_sch = ensure_campaign_schedule(cid)
    notes.append(msg_sch if ok_sch else f"schedule warn: {msg_sch}")

    ok_start, msg_start = start_campaign(cid)
    notes.append(msg_start if ok_start else f"start warn: {msg_start} (start in SmartLead UI if needed)")

    _set_last_error("" if ok_acc and ok_seq else notes[-1])
    return True, cid, " · ".join(notes)


def enroll_lead(
    to_email: str,
    sequence: list[dict[str, Any]],
    *,
    full_name: str = "",
    company: str = "",
    phone: str = "",
    linkedin: str = "",
    title: str = "",
) -> tuple[bool, str]:
    """Enroll one lead into the SmartLead campaign with per-touch custom fields."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Recipient email is missing or invalid."
    if not sequence:
        return False, "Outreach sequence is empty."

    ok_ready, cid, ready_msg = ensure_campaign_ready(steps=len(sequence))
    if not ok_ready or not cid:
        return False, ready_msg

    first, last = _split_name(full_name)
    custom: dict[str, str] = {}
    if title:
        custom["job_title"] = title
    for item in sequence:
        try:
            step = int(item.get("step") or 0)
        except (TypeError, ValueError):
            step = 0
        if step < 1:
            continue
        subject = str(item.get("subject") or "").strip()
        body = str(item.get("body") or "")
        custom[f"ie_subject_{step}"] = subject
        custom[f"ie_body_{step}"] = _plain_to_html(body)

    lead: dict[str, Any] = {
        "email": to_email,
        "first_name": first or "there",
        "last_name": last,
        "company_name": (company or "").strip(),
        "custom_fields": custom,
    }
    if phone:
        lead["phone_number"] = phone.strip()
    if linkedin:
        lead["linkedin_profile"] = linkedin.strip()

    payload = {
        "lead_list": [lead],
        "settings": {
            "ignore_global_block_list": False,
            "ignore_unsubscribe_list": False,
            "ignore_community_bounce_list": False,
            "ignore_duplicate_leads_in_other_campaign": True,
        },
    }
    ok, body, err = _request("POST", f"/campaigns/{cid}/leads", json_body=payload)
    if not ok:
        return False, err

    added = 0
    skipped = 0
    if isinstance(body, dict):
        added = int(body.get("upload_count") or body.get("added_count") or 0)
        skipped = int(body.get("duplicate_count") or body.get("already_added_to_campaign") or 0)
        invalid = body.get("invalid_emails") or []
        if invalid:
            return False, f"SmartLead rejected email(s): {invalid}"

    _set_last_error("")
    if added > 0:
        return True, f"Enrolled in SmartLead campaign {cid} ({added} lead). {ready_msg}"
    if skipped > 0:
        return True, f"Lead already in SmartLead campaign {cid}. {ready_msg}"
    return True, f"SmartLead accepted lead for campaign {cid}. {ready_msg}"


def smartlead_send_test(to_email: str) -> tuple[bool, str]:
    """Enroll a one-step test lead to verify end-to-end connectivity."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Enter a destination email in the sidebar first."
    seq = [
        {
            "step": 1,
            "subject": "IntentEngine / SmartLead test",
            "body": (
                "This is a test enrollment from IntentEngine.\n\n"
                "If SmartLead is connected, this lead appears in your campaign."
            ),
        }
    ]
    return enroll_lead(to_email, seq, full_name="IntentEngine Test", company="IntentEngine")
