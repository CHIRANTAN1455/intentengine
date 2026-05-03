"""In-house outreach logging (no third-party mail providers)."""

from __future__ import annotations

from nocodb_client import append_event, NocoDBError


def personalize_template(template: str, lead: dict) -> str:
    for key, value in lead.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def dispatch_email_internal(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Record an outbound email attempt in NocoDB (events table).
    This does not send real email — it is the in-house operational log.
    """
    try:
        append_event(
            "email_dispatch",
            {"to": to_email, "subject": subject, "body": body},
        )
    except NocoDBError as exc:
        return False, str(exc)
    return True, "Logged to NocoDB (no external send)."
