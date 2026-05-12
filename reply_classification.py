"""
Reply classification: Interested | Not interested | Unsubscribe.
Interested → CRM; others → stop + blacklist (V1: rule-based, no model).
"""
from __future__ import annotations

import re

from config import (
    REPLY_INTERESTED,
    REPLY_NOT_INTERESTED,
    REPLY_UNSUBSCRIBE,
    reply_classifier_llm_enabled,
)
from llm_client import LLMError, classify_reply_with_llm


def classify_reply_text(text: str) -> str:
    if reply_classifier_llm_enabled():
        try:
            label = classify_reply_with_llm(text)
            if label == "Interested":
                return REPLY_INTERESTED
            if label == "Not interested":
                return REPLY_NOT_INTERESTED
            if label == "Unsubscribe":
                return REPLY_UNSUBSCRIBE
        except LLMError:
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
