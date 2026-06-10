"""Per-client branding and copy for IntentEngine Streamlit deployments."""
from __future__ import annotations

from dataclasses import dataclass

from config import BRAND


@dataclass(frozen=True)
class ClientProfile:
    brand: str
    login_brand_html: str
    welcome_lead: str
    pixel_story_lines: tuple[str, str, str]
    hero_subtitle: str


_PROFILES: dict[str, ClientProfile] = {
    "hirequity": ClientProfile(
        brand="hirequity",
        login_brand_html="Welcome to <em>hirequity</em>",
        welcome_lead=(
            "Your live hiring-intent workspace is warming up in the background — job boards, "
            "scoring, and pipeline context — so when you step in, the first rows are already in motion."
        ),
        pixel_story_lines=(
            "Another sales role hits the wire. The city pretends to sleep.",
            "Miles away, a stack blinks: signals stack, tiers settle, someone worth the ping appears.",
            "{brand} is the quiet layer that turns that noise into a room you can own.",
        ),
        hero_subtitle=(
            "Single pipeline: hiring intent, waterfall enrichment, email + Walego, reply intelligence, "
            "and CRM with live performance you can present in the room."
        ),
    ),
}


def get_active_profile() -> ClientProfile:
    key = (BRAND or "hirequity").strip().lower()
    return _PROFILES.get(key, _PROFILES["hirequity"])
