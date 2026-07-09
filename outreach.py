"""Outreach dispatch — MailerSend send + NocoDB audit log."""

from __future__ import annotations

from deliverability import InboxStatus
from config import get_app_settings, mailersend_configured
from mailersend_client import send_email as mailersend_send_email
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
    """
    Send outreach email via MailerSend when configured, then log the attempt
    in NocoDB (events table). In development without MailerSend, logs only.
    """
    inbox = InboxStatus(inbox_id="primary", sent_today=sent_today)
    if not inbox.can_send:
        return False, "Daily send cap reached or deliverability paused."

    settings = get_app_settings()
    if settings.is_production and not mailersend_configured():
        return False, (
            "MailerSend is not configured for production. "
            "Set MAILERSEND_API_TOKEN and MAILERSEND_FROM_EMAIL."
        )

    mailersend_sent = False
    send_msg = ""
    if mailersend_configured():
        ok_send, send_msg = mailersend_send_email(to_email, subject, body)
        if not ok_send:
            return False, send_msg
        mailersend_sent = True

    try:
        append_event(
            "email_dispatch",
            {
                "to": to_email,
                "subject": subject,
                "body": body,
                "mailersend_sent": mailersend_sent,
            },
        )
    except NocoDBError as exc:
        if mailersend_sent:
            return False, f"Email sent but NocoDB log failed: {exc}"
        return False, str(exc)

    if mailersend_sent:
        return True, send_msg
    return True, "Logged to NocoDB (MailerSend not configured — no external send)."
