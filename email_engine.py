"""Email engine — deterministic templates by default.

Templates use placeholders ({company}, {role}, {greeting}, {name}) that resolve
from enriched lead data. SDRs can edit resolved copy per lead in the Outreach step.

If ``EMAIL_LLM_AUGMENT=1`` the LLM may draft sequences; default is OFF.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

from config import BRAND, HIREQUITY_TONE, MAX_EMAILS_PER_LEAD, email_llm_augment_enabled
from llm_client import LLMError, generate_email_sequence_with_llm

GENERIC_GREETING = "Hi there,"

OUTREACH_PLACEHOLDERS = ("company", "role", "greeting", "name", "intent_reason")

DEFAULT_SEQUENCE_TEMPLATES: list[dict[str, Any]] = [
    {
        "step": 1,
        "subject": "Quick one — {company} and {role}",
        "body": (
            "{greeting}\n\n"
            "Noticed {company} is hiring for {role}. We help teams fill those seats "
            "with pre-qualified candidates for that role — without spamming the market.\n\n"
            "Worth a 10-minute chat this week?"
        ),
    },
    {
        "step": 2,
        "subject": "Re: {company} / {role}",
        "body": (
            "{greeting}\n\n"
            "Following up — happy to share 2–3 similar placements we made for "
            "teams hiring {role}. If timing is off, a one-line \"not now\" works.\n\n"
            f"— {BRAND}"
        ),
    },
    {
        "step": 3,
        "subject": "Last note — {company}",
        "body": (
            "{greeting}\n\n"
            "Last ping from me. If filling the {role} role is a priority, I can "
            "send a one-pager. Otherwise I'll close the thread.\n\n"
            f"— {BRAND}"
        ),
    },
]


def default_sequence_templates() -> list[dict[str, Any]]:
    return deepcopy(DEFAULT_SEQUENCE_TEMPLATES)


def _role_hint(row: pd.Series | Mapping[str, Any]) -> str:
    if not isinstance(row, pd.Series):
        row = pd.Series(dict(row))
    for k in ("Hiring role", "Role", "role"):
        if k in row.index and pd.notna(row[k]):
            v = str(row[k]).strip()
            if v:
                return v
    if "Open sales roles" in row.index and pd.notna(row["Open sales roles"]):
        try:
            return f"your open sales hiring ({int(row['Open sales roles'])} roles)"
        except (TypeError, ValueError):
            pass
    return "your sales hiring"


def _company(row: pd.Series | Mapping[str, Any]) -> str:
    if not isinstance(row, pd.Series):
        row = pd.Series(dict(row))
    co = str(row.get("Company", "") or "").strip()
    return co or "your team"


def _greeting(row: pd.Series | Mapping[str, Any]) -> str:
    if not isinstance(row, pd.Series):
        row = pd.Series(dict(row))
    verified = bool(row.get("Enrichment verified"))
    name = str(row.get("Name") or "").strip()
    if verified and name:
        first = name.split()[0]
        return f"Hi {first},"
    return GENERIC_GREETING


def build_placeholder_context(lead: pd.Series | Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(lead, pd.Series):
        lead = pd.Series(dict(lead))
    verified = bool(lead.get("Enrichment verified"))
    name = str(lead.get("Name") or "").strip()
    first = name.split()[0] if verified and name else ""
    return {
        "company": _company(lead),
        "role": _role_hint(lead),
        "greeting": _greeting(lead),
        "name": first or "there",
        "intent_reason": str(lead.get("Intent reason") or "").strip() or "Hiring signals from job boards",
    }


def apply_placeholders(text: str, ctx: Mapping[str, str]) -> str:
    out = str(text or "")
    for key in OUTREACH_PLACEHOLDERS:
        out = out.replace("{" + key + "}", str(ctx.get(key, "")))
    return out


def outreach_lead_key(lead: pd.Series | Mapping[str, Any]) -> str:
    """Stable widget key for a lead. Prefer email; else company + role (avoids collisions)."""
    if not isinstance(lead, pd.Series):
        lead = pd.Series(dict(lead))
    em = str(lead.get("Email") or "").strip().lower()
    if em:
        return re.sub(r"[^a-z0-9@._+-]+", "_", em)
    company = re.sub(r"[^a-z0-9]+", "_", str(lead.get("Company") or "lead").lower()).strip("_")
    role = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(lead.get("Hiring role") or lead.get("Title") or lead.get("Role") or "").lower(),
    ).strip("_")
    intent = re.sub(r"[^a-z0-9]+", "_", str(lead.get("Intent reason") or "")[:40].lower()).strip("_")
    parts = [p for p in (company or "lead", role, intent) if p]
    return "_".join(parts)[:120] or "lead"


def _normalize_templates(templates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    base = default_sequence_templates()
    if not templates:
        return base
    by_step = {int(t.get("step", 0)): dict(t) for t in templates if t.get("step")}
    out: list[dict[str, Any]] = []
    for tpl in base:
        step = int(tpl["step"])
        merged = dict(tpl)
        if step in by_step:
            merged.update({k: v for k, v in by_step[step].items() if k in ("subject", "body", "step")})
        out.append(merged)
    return out


def build_email_sequence(
    lead: pd.Series,
    max_emails: Optional[int] = None,
    *,
    templates: list[dict[str, Any]] | None = None,
    resolved_edits: dict[int, dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    """Return ``{step, subject, body, tone}`` for an outreach sequence.

    * ``templates`` — subject/body strings may contain ``{placeholders}``.
    * ``resolved_edits`` — optional per-step ``{subject, body}`` already filled in
      (from SDR edits in the UI); placeholders in edits are still resolved.
    """
    n = max_emails or MAX_EMAILS_PER_LEAD
    n = min(max(1, int(n)), MAX_EMAILS_PER_LEAD)

    if email_llm_augment_enabled() and not templates and not resolved_edits:
        ctx = build_placeholder_context(lead)
        context = {
            "company": ctx["company"],
            "role_hint": ctx["role"],
            "intent_reason": ctx["intent_reason"],
            "has_verified_name": "true" if ctx["name"] != "there" else "false",
        }
        try:
            seq = generate_email_sequence_with_llm(context, n)
            for item in seq:
                item["tone"] = HIREQUITY_TONE
            return seq[:n]
        except LLMError:
            pass

    tpls = _normalize_templates(templates)[:n]
    ctx = build_placeholder_context(lead)
    seq: list[dict[str, str]] = []
    for tpl in tpls:
        step = int(tpl["step"])
        edit = (resolved_edits or {}).get(step) or {}
        subject_raw = str(edit.get("subject") or tpl.get("subject") or "")
        body_raw = str(edit.get("body") or tpl.get("body") or "")
        seq.append(
            {
                "step": step,
                "subject": apply_placeholders(subject_raw, ctx),
                "body": apply_placeholders(body_raw, ctx),
                "tone": HIREQUITY_TONE,
            }
        )
    return seq
