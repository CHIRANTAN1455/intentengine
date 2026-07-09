"""MailerSend transactional email (outbound outreach).

Sends via POST https://api.mailersend.com/v1/email using the verified domain
configured in ``MAILERSEND_FROM_EMAIL`` (client domain: jobjord.com).
"""
from __future__ import annotations

import html
from typing import Any

import requests

from config import mailersend_api_token, mailersend_from_email, mailersend_from_name

_MAILERSEND_API = "https://api.mailersend.com/v1"
_REQUEST_TIMEOUT = 45

LAST_MAILERSEND_ERROR: str = ""


def _set_last_error(msg: str) -> None:
    global LAST_MAILERSEND_ERROR
    LAST_MAILERSEND_ERROR = msg


def mailersend_last_error() -> str:
    return LAST_MAILERSEND_ERROR


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mailersend_api_token()}",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }


def _plain_to_html(text: str) -> str:
    escaped = html.escape(text or "")
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br/>") + "</p>"


def _extract_error_message(response: requests.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:400]
    if isinstance(body, dict):
        message = body.get("message")
        if message:
            return str(message)[:400]
        errors = body.get("errors")
        if isinstance(errors, dict):
            parts = [f"{k}: {v}" for k, v in errors.items()]
            if parts:
                return "; ".join(parts)[:400]
    return response.text[:400]


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """Send one transactional email. Returns (ok, message)."""
    to_email = (to_email or "").strip()
    subject = (subject or "").strip()
    body = body or ""
    from_email = mailersend_from_email()
    if not mailersend_api_token():
        return False, "MAILERSEND_API_TOKEN is not set."
    if not from_email:
        return False, "MAILERSEND_FROM_EMAIL is not set."
    if not to_email or "@" not in to_email:
        return False, "Recipient email is missing or invalid."
    if not subject:
        return False, "Email subject is empty."

    payload: dict[str, Any] = {
        "from": {"email": from_email, "name": mailersend_from_name()},
        "to": [{"email": to_email}],
        "subject": subject,
        "text": body,
        "html": _plain_to_html(body),
    }
    try:
        r = requests.post(
            f"{_MAILERSEND_API}/email",
            headers=_headers(),
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        _set_last_error(str(exc))
        return False, f"Network error: {exc}"

    if r.status_code in (401, 403):
        msg = f"HTTP {r.status_code}: MailerSend token rejected."
        _set_last_error(msg)
        return False, msg
    if r.status_code >= 400:
        detail = _extract_error_message(r)
        msg = f"HTTP {r.status_code}: {detail}"
        _set_last_error(msg)
        return False, msg

    _set_last_error("")
    return True, f"Sent via MailerSend to {to_email}."


def mailersend_quick_probe() -> tuple[bool, str]:
    """List domains to confirm the API token works (no email sent)."""
    if not mailersend_api_token():
        return False, "MAILERSEND_API_TOKEN is not set in env or Streamlit secrets."
    try:
        r = requests.get(
            f"{_MAILERSEND_API}/domains",
            headers=_headers(),
            params={"page": 1, "limit": 10},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    if r.status_code in (401, 403):
        return False, f"HTTP {r.status_code}: token rejected."
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}: {_extract_error_message(r)}"
    try:
        body = r.json()
    except ValueError:
        return False, "MailerSend returned non-JSON response."
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return True, "OK — MailerSend API responded."

    verified = [
        str(d.get("name", "")).strip()
        for d in data
        if isinstance(d, dict) and str(d.get("status", "")).lower() == "verified"
    ]
    from_email = mailersend_from_email()
    if from_email:
        domain = from_email.split("@", 1)[-1].lower()
        if domain and not any(domain == v.lower() or domain.endswith("." + v.lower()) for v in verified if v):
            return (
                True,
                f"Token OK — {len(data)} domain(s) listed; "
                f"confirm {domain} is verified in MailerSend.",
            )
    if verified:
        return True, f"OK — verified domain(s): {', '.join(verified[:5])}."
    names = [str(d.get("name", "")).strip() for d in data if isinstance(d, dict) and d.get("name")]
    if names:
        return True, f"OK — domain(s) on account: {', '.join(names[:5])} (check verification status)."
    return True, "OK — MailerSend API responded (no domains returned)."


def mailersend_send_test(to_email: str) -> tuple[bool, str]:
    """Send a single test message to confirm end-to-end delivery."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Enter a destination email in the sidebar first."
    subject = "IntentEngine / MailerSend test"
    body = (
        "This is a test message from IntentEngine.\n\n"
        "If you received this, MailerSend is configured correctly."
    )
    return send_email(to_email, subject, body)
