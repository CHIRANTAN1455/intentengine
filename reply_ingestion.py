"""Reply ingestion stub for in-house build (no IMAP). Paste replies in the UI instead."""

from __future__ import annotations


def fetch_recent_replies(recipient_emails: set[str], limit: int = 100) -> list[dict[str, str]]:
    return []
