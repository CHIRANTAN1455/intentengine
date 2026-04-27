"""HireQuity – Intent Outbound Engine (V1) central constants."""

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
