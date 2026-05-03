"""
Reply classification: Interested | Not interested | Unsubscribe.
Interested → CRM; others → stop + blacklist (V1: rule-based, no model).
"""
from __future__ import annotations

import re

from config import REPLY_INTERESTED, REPLY_NOT_INTERESTED, REPLY_UNSUBSCRIBE
from openrouter_client import OpenRouterError, classify_reply_with_openrouter


def classify_reply_text(text: str) -> str:
    try:
        label = classify_reply_with_openrouter(text)
        if label == "Interested":
            return REPLY_INTERESTED
        if label == "Not interested":
            return REPLY_NOT_INTERESTED
        if label == "Unsubscribe":
            return REPLY_UNSUBSCRIBE
    except OpenRouterError:
        # Fallback keeps pipeline working during transient provider issues.
        pass

    t = (text or "").strip().lower()
    if not t:
        return REPLY_NOT_INTERESTED
    if re.search(r"unsub|remove me|stop (email|mailing|contacting)", t):
        return REPLY_UNSUBSCRIBE
    if re.search(r"\bnot interested\b|not a fit|no thank|not looking", t):
        return REPLY_NOT_INTERESTED
    if re.search(
        r"\b(yes|sounds good|let\'?s|book|call|interested|schedule|meeting|zoom)\b", t
    ):
        return REPLY_INTERESTED
    if len(t) < 8:
        return REPLY_NOT_INTERESTED
    return REPLY_NOT_INTERESTED  # default conservative


def crm_eligible(label: str) -> bool:
    from config import REPLY_INTERESTED

    return label == REPLY_INTERESTED
