"""Outreach dispatch — SmartLead enroll + NocoDB audit log."""

from __future__ import annotations

from typing import Any

from deliverability import InboxStatus
from config import get_app_settings, smartlead_configured
from smartlead_client import enroll_lead as smartlead_enroll_lead
from nocodb_rest import append_event, NocoDBError


def personalize_template(template: str, lead: dict) -> str:
    for key, value in lead.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def dispatch_email_internal(
    to_email: str,
    subject: str,
    body: str,
    *,
    sent_today: int = 0,
) -> tuple[bool, str]:
    """Backward-compatible single-touch wrapper → SmartLead one-step enroll."""
    return dispatch_outreach_lead(
        to_email,
        [{"step": 1, "subject": subject, "body": body}],
        sent_today=sent_today,
    )


def dispatch_outreach_lead(
    to_email: str,
    sequence: list[dict[str, Any]],
    *,
    full_name: str = "",
    company: str = "",
    phone: str = "",
    linkedin: str = "",
    title: str = "",
    sent_today: int = 0,
) -> tuple[bool, str]:
    """
    Enroll a lead in SmartLead with the edited outreach sequence, then log to NocoDB.
    In development without SmartLead, logs only.
    """
    inbox = InboxStatus(inbox_id="primary", sent_today=sent_today)
    if not inbox.can_send:
        return False, "Daily send cap reached or deliverability paused."

    settings = get_app_settings()
    if settings.is_production and not smartlead_configured():
        return False, (
            "SmartLead is not configured for production. "
            "Set SMARTLEAD_API_KEY (and optionally SMARTLEAD_CAMPAIGN_ID)."
        )

    smartlead_sent = False
    send_msg = ""
    if smartlead_configured():
        ok_send, send_msg = smartlead_enroll_lead(
            to_email,
            sequence,
            full_name=full_name,
            company=company,
            phone=phone,
            linkedin=linkedin,
            title=title,
        )
        if not ok_send:
            return False, send_msg
        smartlead_sent = True

    try:
        append_event(
            "email_dispatch",
            {
                "to": to_email,
                "sequence": [
                    {
                        "step": s.get("step"),
                        "subject": s.get("subject"),
                        "body": s.get("body"),
                    }
                    for s in sequence
                ],
                "smartlead_enrolled": smartlead_sent,
                "provider": "smartlead" if smartlead_sent else "log_only",
            },
        )
    except NocoDBError as exc:
        if smartlead_sent:
            return False, f"Lead enrolled but NocoDB log failed: {exc}"
        return False, str(exc)

    if smartlead_sent:
        return True, send_msg
    return True, "Logged to NocoDB (SmartLead not configured — no external enroll)."
