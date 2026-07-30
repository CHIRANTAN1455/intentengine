"""Email engine — deterministic templates by default.

Templates use placeholders ({company}, {role}, {greeting}, {name}) that resolve
from enriched lead data. SDRs can edit resolved copy per lead in the Outreach step,
or maintain separate sequences per role family (AE, SDR/BDR, sales leaders).

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

# Role-family keys used for per-role sequence templates.
ROLE_SEQUENCE_DEFAULT = "default"
ROLE_SEQUENCE_AE = "ae"
ROLE_SEQUENCE_SDR_BDR = "sdr_bdr"
ROLE_SEQUENCE_SALES_LEADER = "sales_leader"

ROLE_SEQUENCE_LABELS: dict[str, str] = {
    ROLE_SEQUENCE_DEFAULT: "Default (all other roles)",
    ROLE_SEQUENCE_AE: "Account Executive / AE",
    ROLE_SEQUENCE_SDR_BDR: "SDR / BDR",
    ROLE_SEQUENCE_SALES_LEADER: "Sales manager / director / VP",
}

ROLE_SEQUENCE_KEYS: tuple[str, ...] = tuple(ROLE_SEQUENCE_LABELS.keys())

# Strip location / seniority fluff that makes subjects read like job-board spam.
_ROLE_NOISE = re.compile(
    r"""(?ix)
    \b(
        remote|hybrid|onsite|on[\s-]?site|
        toronto|vancouver|montreal|calgary|ottawa|edmonton|
        canada|united\s+states|usa|us|uk|
        mid[\s-]?market|enterprise|smb|startup|
        full[\s-]?time|part[\s-]?time|contract|permanent|
        \d+\+?\s*years?
    )\b
    """
)
_ROLE_SEP_SPLIT = re.compile(r"\s*[|/\u2013\u2014\-–—]\s*")
_MULTI_SPACE = re.compile(r"\s+")


def _clean_role_raw(raw: str) -> str:
    """Take the first posting fragment and drop board noise."""
    text = str(raw or "").strip()
    if not text:
        return ""
    # Multiple roles often joined with " · " or ";" — keep the first.
    for sep in (" · ", " • ", ";", "\n"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    parts = _ROLE_SEP_SPLIT.split(text)
    text = parts[0].strip() if parts else text
    text = _ROLE_NOISE.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text).strip(" ,.-")
    # Cap length so subjects stay human.
    if len(text) > 42:
        text = text[:42].rsplit(" ", 1)[0].strip() or text[:42]
    return text


def short_role(raw: str) -> str:
    """Map a long job-board title to a short label for email copy."""
    cleaned = _clean_role_raw(raw)
    if not cleaned:
        return "sales"
    r = cleaned.lower()

    if re.search(r"\b(sdr|sales development)\b", r):
        return "SDR"
    if re.search(r"\b(bdr|business development rep)\b", r):
        return "BDR"
    if re.search(r"\b(account exec|account executive|\bae\b)\b", r):
        return "AE"
    if re.search(r"\b(inside sales)\b", r):
        return "inside sales"
    if re.search(r"\b(field sales)\b", r):
        return "field sales"
    if re.search(r"\b(sales rep|sales representative)\b", r):
        return "sales rep"
    if re.search(r"\b(vp|vice president).{0,20}sales\b|\bhead of sales\b|\bchief revenue\b|\bcro\b", r):
        return "sales leadership"
    if re.search(r"\b(sales director|director of sales)\b", r):
        return "Sales Director"
    if re.search(r"\b(sales manager|manager[, ].*sales)\b", r):
        return "Sales Manager"
    if re.search(r"\bbusiness development\b", r):
        return "BD"
    # Fall back to cleaned short title (title-cased lightly).
    return cleaned


def detect_role_family(raw: str) -> str:
    """Which sequence bucket a hiring-role string belongs to."""
    r = str(raw or "").lower()
    if re.search(r"\b(sdr|bdr|sales development|business development rep)\b", r):
        return ROLE_SEQUENCE_SDR_BDR
    if re.search(r"\b(account exec|account executive|\bae\b)\b", r):
        return ROLE_SEQUENCE_AE
    if re.search(
        r"\b(vp|vice president|head of|director|manager|chief revenue|\bcro\b).{0,24}sales"
        r"|\bsales (vp|director|manager)\b",
        r,
    ):
        return ROLE_SEQUENCE_SALES_LEADER
    return ROLE_SEQUENCE_DEFAULT


def _sequence_touch(
    step: int,
    subject: str,
    body: str,
) -> dict[str, Any]:
    return {"step": step, "subject": subject, "body": body}


# Punchy, human defaults — short roles, one clear ask, no job-board title dumps.
_DEFAULT_SEQ: list[dict[str, Any]] = [
    _sequence_touch(
        1,
        "{company} — quick question",
        (
            "{greeting}\n\n"
            "Saw {company} is hiring for {role}. We fill those seats with "
            "pre-vetted people — no spray-and-pray lists.\n\n"
            "Open to 10 minutes this week?"
        ),
    ),
    _sequence_touch(
        2,
        "Re: {company}",
        (
            "{greeting}\n\n"
            "Circling back — I can send 2–3 profiles that match what you're "
            "hiring for. One-line \"not now\" is fine too.\n\n"
            f"— {BRAND}"
        ),
    ),
    _sequence_touch(
        3,
        "Closing the loop — {company}",
        (
            "{greeting}\n\n"
            "Last note from me. If the {role} seat still matters, I'll send a "
            "one-pager. Otherwise I'll step back.\n\n"
            f"— {BRAND}"
        ),
    ),
]

_AE_SEQ: list[dict[str, Any]] = [
    _sequence_touch(
        1,
        "AE seat at {company}",
        (
            "{greeting}\n\n"
            "Noticed the AE opening at {company}. We place Account Executives "
            "who've closed similar deals — stage-fit, not generic resumes.\n\n"
            "Worth a quick call?"
        ),
    ),
    _sequence_touch(
        2,
        "Re: AE hiring at {company}",
        (
            "{greeting}\n\n"
            "Happy to share 2–3 AE profiles that look like a fit for {company}. "
            "If timing's off, just say so.\n\n"
            f"— {BRAND}"
        ),
    ),
    _sequence_touch(
        3,
        "Last note — AE at {company}",
        (
            "{greeting}\n\n"
            "I'll close this out unless you want those AE profiles. "
            "One reply either way works.\n\n"
            f"— {BRAND}"
        ),
    ),
]

_SDR_BDR_SEQ: list[dict[str, Any]] = [
    _sequence_touch(
        1,
        "SDR/BDR hiring at {company}",
        (
            "{greeting}\n\n"
            "Saw you're hiring SDRs/BDRs at {company}. We send pipeline-ready "
            "reps who already know outbound — so ramp isn't a coin flip.\n\n"
            "Got 10 minutes this week?"
        ),
    ),
    _sequence_touch(
        2,
        "Re: SDR/BDR at {company}",
        (
            "{greeting}\n\n"
            "I can send a shortlist of SDR/BDR profiles matched to your motion. "
            "Want me to?\n\n"
            f"— {BRAND}"
        ),
    ),
    _sequence_touch(
        3,
        "Closing the loop — {company}",
        (
            "{greeting}\n\n"
            "Last ping. If the SDR/BDR seat is still open, I'll send profiles. "
            "If not, I'll leave you alone.\n\n"
            f"— {BRAND}"
        ),
    ),
]

_SALES_LEADER_SEQ: list[dict[str, Any]] = [
    _sequence_touch(
        1,
        "Sales leadership seat — {company}",
        (
            "{greeting}\n\n"
            "Noticed {company} is hiring into sales leadership. We place "
            "managers and directors who can hire and ramp a team, not just "
            "carry a bag.\n\n"
            "Open to a short calibration?"
        ),
    ),
    _sequence_touch(
        2,
        "Re: {company} sales leadership",
        (
            "{greeting}\n\n"
            "I can share 2–3 leadership profiles with relevant ramp / team "
            "builds. Useful, or bad timing?\n\n"
            f"— {BRAND}"
        ),
    ),
    _sequence_touch(
        3,
        "Last note — {company}",
        (
            "{greeting}\n\n"
            "I'll step back unless you want those profiles. "
            "Either way — thanks for reading.\n\n"
            f"— {BRAND}"
        ),
    ),
]

DEFAULT_SEQUENCES_BY_ROLE: dict[str, list[dict[str, Any]]] = {
    ROLE_SEQUENCE_DEFAULT: _DEFAULT_SEQ,
    ROLE_SEQUENCE_AE: _AE_SEQ,
    ROLE_SEQUENCE_SDR_BDR: _SDR_BDR_SEQ,
    ROLE_SEQUENCE_SALES_LEADER: _SALES_LEADER_SEQ,
}

# Back-compat alias used by older call sites.
DEFAULT_SEQUENCE_TEMPLATES = _DEFAULT_SEQ


def default_sequence_templates(family: str | None = None) -> list[dict[str, Any]]:
    key = family if family in DEFAULT_SEQUENCES_BY_ROLE else ROLE_SEQUENCE_DEFAULT
    return deepcopy(DEFAULT_SEQUENCES_BY_ROLE[key])


def default_sequences_by_role() -> dict[str, list[dict[str, Any]]]:
    return {k: deepcopy(v) for k, v in DEFAULT_SEQUENCES_BY_ROLE.items()}


def _hiring_role_raw(row: pd.Series | Mapping[str, Any]) -> str:
    if not isinstance(row, pd.Series):
        row = pd.Series(dict(row))
    for k in ("Hiring role", "Role", "role"):
        if k in row.index and pd.notna(row[k]):
            v = str(row[k]).strip()
            if v:
                return v
    return ""


def _role_hint(row: pd.Series | Mapping[str, Any]) -> str:
    raw = _hiring_role_raw(row)
    if raw:
        return short_role(raw)
    if not isinstance(row, pd.Series):
        row = pd.Series(dict(row))
    if "Open sales roles" in row.index and pd.notna(row["Open sales roles"]):
        try:
            return f"sales ({int(row['Open sales roles'])} seats)"
        except (TypeError, ValueError):
            pass
    return "sales"


def role_family_for_lead(lead: pd.Series | Mapping[str, Any]) -> str:
    return detect_role_family(_hiring_role_raw(lead))


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


def _normalize_templates(templates: list[dict[str, Any]] | None, family: str | None = None) -> list[dict[str, Any]]:
    base = default_sequence_templates(family)
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


def resolve_templates_for_lead(
    lead: pd.Series | Mapping[str, Any],
    sequences_by_role: Mapping[str, list[dict[str, Any]]] | None = None,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pick the best sequence for a lead: role family → default → built-in."""
    family = role_family_for_lead(lead)
    by_role = sequences_by_role or {}
    if family in by_role and isinstance(by_role[family], list) and by_role[family]:
        return _normalize_templates(list(by_role[family]), family)
    if ROLE_SEQUENCE_DEFAULT in by_role and isinstance(by_role[ROLE_SEQUENCE_DEFAULT], list) and by_role[ROLE_SEQUENCE_DEFAULT]:
        return _normalize_templates(list(by_role[ROLE_SEQUENCE_DEFAULT]), ROLE_SEQUENCE_DEFAULT)
    if fallback:
        return _normalize_templates(fallback, family)
    return default_sequence_templates(family)


def build_email_sequence(
    lead: pd.Series,
    max_emails: Optional[int] = None,
    *,
    templates: list[dict[str, Any]] | None = None,
    sequences_by_role: Mapping[str, list[dict[str, Any]]] | None = None,
    resolved_edits: dict[int, dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    """Return ``{step, subject, body, tone}`` for an outreach sequence.

    * ``templates`` — subject/body strings may contain ``{placeholders}``.
    * ``sequences_by_role`` — optional map of role-family → templates; used when
      ``templates`` is not passed explicitly.
    * ``resolved_edits`` — optional per-step ``{subject, body}`` already filled in
      (from SDR edits in the UI); placeholders in edits are still resolved.
    """
    n = max_emails or MAX_EMAILS_PER_LEAD
    n = min(max(1, int(n)), MAX_EMAILS_PER_LEAD)

    if email_llm_augment_enabled() and not templates and not resolved_edits and not sequences_by_role:
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

    if templates is not None:
        tpls = _normalize_templates(templates, role_family_for_lead(lead))[:n]
    else:
        tpls = resolve_templates_for_lead(lead, sequences_by_role)[:n]
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
