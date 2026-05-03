"""Central config and constants for IntentEngine."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

BRAND = "HireQuity"
PRODUCT = "Intent Outbound Engine"

# Job boards we aggregate (V1: mock or adapter pluggable; real scrapers go behind these flags)
JOB_SOURCES = ("linkedin_jobs", "indeed", "glassdoor")

# Sales hiring roles to match
SALES_ROLE_KEYWORDS = (
    "sales rep",
    "account executive",
    "sdr",
    "bdr",
    "ae",
    "account exec",
    "business development",
    "outbound",
)

# Intent tiers
TIER_HIGH = "High"
TIER_MEDIUM = "Medium"
TIER_LOW = "Low"

# Email sequence
MAX_EMAILS_PER_LEAD = 3
HIREQUITY_TONE = "direct, short, one clear CTA—no buzzwords"

# Deliverability
MAX_EMAILS_PER_INBOX_PER_DAY = 30
MIN_EMAILS_PER_INBOX_PER_DAY = 20  # used as floor for display / planning

# Walego: LinkedIn execution only; no duplicate messaging in-app
WALEGO_HANDOFF_KEY = "walego_payload"

# CRM: only interested leads
CRM_STATUSES = ("Interested", "Booked", "Closed")

# Reply classes
REPLY_INTERESTED = "Interested"
REPLY_NOT_INTERESTED = "Not interested"
REPLY_UNSUBSCRIBE = "Unsubscribe"


@dataclass(frozen=True)
class AppSettings:
    app_env: str

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@dataclass(frozen=True)
class OpenRouterSettings:
    api_key: str
    model: str
    base_url: str
    http_referer: str
    app_title: str
    timeout_seconds: int


@dataclass(frozen=True)
class NocoDBSettings:
    base_url: str
    api_token: str
    table_id: str
    events_table_id: str
    field_session_id: str
    field_step: str
    field_payload_json: str
    field_event_type: str
    field_event_payload_json: str


def _read_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _read_optional_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return (value or "").strip()


def get_app_settings() -> AppSettings:
    return AppSettings(app_env=_read_env("APP_ENV", "development"))


def get_openrouter_settings() -> OpenRouterSettings:
    timeout_raw = _read_env("OPENROUTER_TIMEOUT_SECONDS", "25")
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise RuntimeError("OPENROUTER_TIMEOUT_SECONDS must be an integer.") from exc
    return OpenRouterSettings(
        api_key=_read_env("OPENROUTER_API_KEY"),
        model=_read_env("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        base_url=_read_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"),
        http_referer=_read_env("OPENROUTER_HTTP_REFERER", "https://intentengine.local"),
        app_title=_read_env("OPENROUTER_APP_TITLE", PRODUCT),
        timeout_seconds=timeout_seconds,
    )


def get_nocodb_settings() -> NocoDBSettings:
    return NocoDBSettings(
        base_url=_read_env("NOCODB_BASE_URL", "https://app.nocodb.com"),
        api_token=_read_env("NOCODB_API_TOKEN"),
        table_id=_read_env("NOCODB_PIPELINE_TABLE_ID"),
        events_table_id=_read_optional_env("NOCODB_EVENTS_TABLE_ID"),
        field_session_id=_read_env("NOCODB_FIELD_SESSION_ID", "session_id"),
        field_step=_read_env("NOCODB_FIELD_STEP", "step"),
        field_payload_json=_read_env("NOCODB_FIELD_PAYLOAD_JSON", "payload_json"),
        field_event_type=_read_env("NOCODB_FIELD_EVENT_TYPE", "event_type"),
        field_event_payload_json=_read_env("NOCODB_FIELD_EVENT_PAYLOAD_JSON", "payload_json"),
    )
