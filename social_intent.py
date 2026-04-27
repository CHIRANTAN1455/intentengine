"""
Social intent: LinkedIn posts/comments mentioning hiring (V1: simulated feed).
Merges into the same company-level intent pipeline.
"""
from __future__ import annotations

import pandas as pd

_MOCK_SOCIAL: list[dict] = [
    {
        "Company": "Nexora",
        "Signal": "hiring more SDRs this quarter to scale outbound",
        "Source": "linkedin_post",
    },
    {
        "Company": "ScaleHire",
        "Signal": "we need AEs to cover new territories",
        "Source": "linkedin_comment",
    },
    {
        "Company": "PulseLabs",
        "Signal": "growing the sales team — DM if you know a great BDR",
        "Source": "linkedin_post",
    },
]


def fetch_social_intent() -> pd.DataFrame:
    return pd.DataFrame(_MOCK_SOCIAL)
