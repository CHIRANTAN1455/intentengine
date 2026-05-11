"""
Deliverability layer: domain/inbox capacity (V1: checks + config).
If warm-up/SPF/DKIM are not healthy, outbound should pause.
"""

from config import MAX_EMAILS_PER_INBOX_PER_DAY, MIN_EMAILS_PER_INBOX_PER_DAY


class InboxStatus:
    """Plain class (not @dataclass) to avoid Streamlit/hosted import edge cases with dataclasses."""

    __slots__ = ("inbox_id", "sent_today", "max_per_day", "spf_ok", "dkim_ok", "warmup_healthy")

    def __init__(
        self,
        inbox_id: str,
        sent_today: int,
        *,
        max_per_day: int = MAX_EMAILS_PER_INBOX_PER_DAY,
        spf_ok: bool = True,
        dkim_ok: bool = True,
        warmup_healthy: bool = True,
    ) -> None:
        self.inbox_id = inbox_id
        self.sent_today = sent_today
        self.max_per_day = max_per_day
        self.spf_ok = spf_ok
        self.dkim_ok = dkim_ok
        self.warmup_healthy = warmup_healthy

    @property
    def can_send(self) -> bool:
        return self.spf_ok and self.dkim_ok and self.warmup_healthy and self.sent_today < self.max_per_day

    @property
    def remaining(self) -> int:
        return max(0, self.max_per_day - self.sent_today)


def plan_capacity(sent_today: int) -> str:
    """Human-readable guardrail for UI."""
    if sent_today >= MAX_EMAILS_PER_INBOX_PER_DAY:
        return "Inbox at daily cap — pause sends until tomorrow."
    if sent_today >= MIN_EMAILS_PER_INBOX_PER_DAY:
        return "Approaching daily limit — only priority sends."
    return "Within safe daily volume (20–30 per inbox)."
