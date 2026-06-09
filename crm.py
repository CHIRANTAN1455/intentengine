"""
CRM: post-enrich records use a status layer so SDRs see assignments but do not
manually work leads until automation releases coordination (reply, exhaustion,
or high-intent review).
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

import pandas as pd

from enrichment import job_board_linkedin_safe

from config import (
    CRM_TOUCHES_BEFORE_MANUAL_CALL,
    CRM_STATUSES,
    HIGH_INTENT_SDR_PAUSE_SCORE,
    LEAD_STATUS_AWAITING_VERIFIED_CONTACT,
    LEAD_STATUS_DNC,
    LEAD_STATUS_HIGH_INTENT_REVIEW,
    LEAD_STATUS_IN_SEQUENCE,
    LEAD_STATUS_MANUAL_RECOMMENDED,
    LEAD_STATUS_QUEUED,
    LEAD_STATUS_REPLIED,
    OUTREACH_LOCK_ACTIVE,
    OUTREACH_LOCK_RELEASED,
    REPLY_INTERESTED,
    REPLY_NOT_INTERESTED,
    REPLY_UNSUBSCRIBE,
    SEQUENCE_PAUSED_HIGH_INTENT,
    SEQUENCE_PENDING,
)


def _id_for(lead: pd.Series) -> str:
    raw = f"{lead.get('Email', '')}{lead.get('Name', '')}{lead.get('Company', '')}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _email_key(rec: dict[str, Any]) -> str:
    return str(rec.get("email") or "").strip().lower()


def _dedup_key(rec: dict[str, Any]) -> str:
    """Stable dedup key. Prefer email; fall back to company so that leads
    without a verified email still merge cleanly across re-runs."""
    em = _email_key(rec)
    if em:
        return f"email:{em}"
    co = str(rec.get("company") or "").strip().lower()
    if co:
        return f"company:{co}"
    rid = str(rec.get("id") or "").strip().lower()
    if rid:
        return f"id:{rid}"
    return ""


def _by_email(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_email_key(r): r for r in records if _email_key(r)}


def _by_key(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        k = _dedup_key(r)
        if k:
            out[k] = r
    return out


def _log_line(msg: str) -> str:
    return f"{datetime.utcnow().isoformat()}Z — {msg}"


def _deal_status_default() -> str:
    return "Interested" if "Interested" in CRM_STATUSES else str(CRM_STATUSES[0])


def build_crm_record(
    lead: pd.Series,
    interaction_log: str,
    status: str = "Interested",
) -> dict[str, Any]:
    """Legacy shape: interested-only rows. Prefer seed_post_enrich_row for new pipeline."""
    if status not in CRM_STATUSES:
        status = _deal_status_default()
    base = seed_post_enrich_row(lead, assigned_sdr="—", interaction_log=interaction_log)
    base["deal_status"] = status
    base["status"] = status
    base["lead_status"] = LEAD_STATUS_REPLIED
    base["outreach_lock"] = OUTREACH_LOCK_RELEASED
    base["sequence_status"] = "Replied — routed to SDR"
    base["sdr_next_action"] = "Needs SDR follow-up"
    base["sdr_manual_allowed"] = True
    return base


def seed_post_enrich_row(
    lead: pd.Series,
    assigned_sdr: str,
    interaction_log: str = "",
) -> dict[str, Any]:
    """
    After enrich → CRM: queued for automation; SDR visible but must not manually touch yet.

    Behaviour:
        * High intent (score) → sequence paused for SDR review (Scenario C).
        * No verified email → sequence paused as "Awaiting verified contact"
          (Scenario D, added when AI-generated contacts were removed).
        * Otherwise → queued, automation coordinates first touches.
    """
    score = 0.0
    if "Intent score" in lead.index and pd.notna(lead.get("Intent score")):
        try:
            score = float(lead.get("Intent score"))
        except (TypeError, ValueError):
            score = 0.0

    email_addr = str(lead.get("Email", "") or "").strip()
    enrichment_verified = bool(lead.get("Enrichment verified"))
    contact_verified = enrichment_verified and bool(email_addr)
    high_hold = score >= HIGH_INTENT_SDR_PAUSE_SCORE

    if not contact_verified:
        lead_status = LEAD_STATUS_AWAITING_VERIFIED_CONTACT
        sequence_status = "Paused — awaiting verified contact source"
        sdr_next = (
            "No verified contact yet. Provide a real Email / Name from a verified "
            "data source before the sequence will run."
        )
        seq_paused = True
        manual_ok = False
        log = _log_line("CRM: created post-enrich — awaiting verified contact (sequence paused).")
    elif high_hold:
        lead_status = LEAD_STATUS_HIGH_INTENT_REVIEW
        sequence_status = SEQUENCE_PAUSED_HIGH_INTENT
        sdr_next = "High-intent lead: review now. Automated sequence paused until SDR clears."
        seq_paused = True
        manual_ok = True
        log = _log_line("CRM: created post-enrich — high intent hold (sequence paused).")
    else:
        lead_status = LEAD_STATUS_QUEUED
        sequence_status = SEQUENCE_PENDING
        sdr_next = "Do not manually touch yet — automation coordinates first touches."
        seq_paused = False
        manual_ok = False
        log = _log_line("CRM: created post-enrich — queued for outreach (lock active).")

    hist_parts = [log]
    if interaction_log:
        hist_parts.append(interaction_log)
    li = str(lead.get("LinkedIn", "") or "").strip()
    if not enrichment_verified and li and not job_board_linkedin_safe(li):
        li = ""
    hiring_role = str(lead.get("Hiring role", "") or "").strip()
    contact_title = ""
    if enrichment_verified:
        contact_title = str(lead.get("Title", "") or "").strip()
        if contact_title and hiring_role and contact_title == hiring_role:
            # Pre-Apollo rows duplicate posting text in Title; keep blank until distinct.
            contact_title = ""
    return {
        "id": _id_for(lead),
        "name": str(lead.get("Name", "") or ""),
        "company": str(lead.get("Company", "") or ""),
        "email": email_addr,
        "linkedin": li,
        "phone": str(lead.get("Phone", "") or "") if enrichment_verified else "",
        "contact_title": contact_title,
        "intent_reason": str(lead.get("Intent reason", "") or ""),
        "intent_score": score,
        "intent_tier": str(lead.get("Intent tier", "") or ""),
        "hiring_role": hiring_role,
        "lead_status": lead_status,
        "outreach_lock": OUTREACH_LOCK_ACTIVE if contact_verified else OUTREACH_LOCK_RELEASED,
        "assigned_sdr": (assigned_sdr or "").strip() or "Unassigned",
        "sequence_status": sequence_status,
        "sequence_paused": seq_paused,
        "touches_sent": 0,
        "sdr_next_action": sdr_next,
        "sdr_manual_allowed": manual_ok,
        "call_task_created": False,
        "interaction_history": " | ".join(hist_parts),
        "deal_status": "Pipeline",
        "status": "Pipeline",
        "enrichment_verified": enrichment_verified,
        "pushed_at": datetime.utcnow().isoformat() + "Z",
    }


def seed_crm_from_enriched(
    leads: pd.DataFrame,
    assigned_sdr: str,
    blacklist: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if leads is None or leads.empty:
        return out
    seen_keys: set[str] = set()
    for _, lead in leads.iterrows():
        em = str(lead.get("Email") or "").strip().lower()
        if em and em in blacklist:
            continue
        row = seed_post_enrich_row(lead, assigned_sdr=assigned_sdr)
        key = _dedup_key(row)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        out.append(row)
    return out


def apply_dispatch_to_records(
    records: list[dict[str, Any]],
    touches_by_email: dict[str, int],
) -> list[dict[str, Any]]:
    """When sequence touches are logged: In Sequence + per-touch sequence line."""
    touches_norm = {str(k).strip().lower(): int(v) for k, v in touches_by_email.items()}
    out: list[dict[str, Any]] = []
    for r in records:
        rec = dict(r)
        k = _email_key(rec)
        if not k:
            out.append(rec)
            continue
        n = int(touches_norm.get(k, 0))
        if n <= 0 or rec.get("sequence_paused"):
            out.append(rec)
            continue
        rec["touches_sent"] = n
        rec["lead_status"] = LEAD_STATUS_IN_SEQUENCE
        rec["sequence_status"] = f"Email {n} sent"
        rec["outreach_lock"] = OUTREACH_LOCK_ACTIVE
        rec["sdr_next_action"] = "Do not manually touch yet — sequence in progress."
        rec["sdr_manual_allowed"] = False
        prev = str(rec.get("interaction_history") or "")
        rec["interaction_history"] = (
            prev + " | " + _log_line(f"Dispatch: logged {n} email touch(es).")
        ).strip(" |")
        out.append(rec)
    return out


def refresh_crm_after_replies(
    records: list[dict[str, Any]],
    replies: list[dict[str, Any]],
    *,
    touch_threshold: int = CRM_TOUCHES_BEFORE_MANUAL_CALL,
) -> list[dict[str, Any]]:
    """
    Merge reply labels + no-reply exhaustion into existing CRM rows.
    Scenario A: positive reply → Replied + SDR follow-up.
    Scenario B: max touches and no positive reply (including no reply row) → manual call.
    """
    reply_by_email: dict[str, dict[str, Any]] = {}
    for r in replies or []:
        em = str(r.get("email") or "").strip().lower()
        if em:
            reply_by_email[em] = r

    out: list[dict[str, Any]] = []
    for r in records:
        rec = dict(r)
        key = _email_key(rec)
        if not key:
            out.append(rec)
            continue

        rpl = reply_by_email.get(key)
        label = str(rpl.get("label") or "") if rpl else ""
        touches = int(rec.get("touches_sent") or 0)

        if label == REPLY_UNSUBSCRIBE:
            rec["lead_status"] = LEAD_STATUS_DNC
            rec["outreach_lock"] = OUTREACH_LOCK_RELEASED
            rec["sdr_next_action"] = "Unsubscribed — do not contact."
            rec["sdr_manual_allowed"] = False
            rec["deal_status"] = "Closed"
            rec["status"] = "Closed"
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (
                prev + " | " + _log_line("Unsubscribe — removed from active outreach.")
            ).strip(" |")
            out.append(rec)
            continue

        if label == REPLY_INTERESTED:
            rec["lead_status"] = LEAD_STATUS_REPLIED
            rec["sequence_status"] = "Replied"
            rec["outreach_lock"] = OUTREACH_LOCK_RELEASED
            rec["sdr_next_action"] = "Needs SDR follow-up"
            rec["sdr_manual_allowed"] = True
            rec["deal_status"] = "Interested"
            rec["status"] = "Interested"
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (
                prev + " | " + _log_line("Reply classified positive — SDR may take over.")
            ).strip(" |")
            out.append(rec)
            continue

        if label == REPLY_NOT_INTERESTED:
            rec["lead_status"] = "Not interested"
            rec["outreach_lock"] = OUTREACH_LOCK_RELEASED
            rec["sdr_next_action"] = "No further automated sequence; optional SDR nurture only."
            rec["sdr_manual_allowed"] = True
            rec["deal_status"] = "Closed"
            rec["status"] = "Closed"
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (
                prev + " | " + _log_line("Reply: not interested.")
            ).strip(" |")
            out.append(rec)
            continue

        if (
            touches >= touch_threshold
            and rec.get("lead_status") not in (LEAD_STATUS_REPLIED, LEAD_STATUS_DNC)
            and rec.get("lead_status") != "Not interested"
        ):
            rec["lead_status"] = LEAD_STATUS_MANUAL_RECOMMENDED
            rec["sequence_status"] = f"Completed {touches} touches — no positive reply"
            rec["outreach_lock"] = OUTREACH_LOCK_RELEASED
            rec["call_task_created"] = True
            rec["sdr_next_action"] = "Call task created — manual outreach recommended."
            rec["sdr_manual_allowed"] = True
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (
                prev + " | " + _log_line("Exhaustion: no positive reply after max touches.")
            ).strip(" |")

        out.append(rec)
    return out


def merge_seed_with_existing(
    existing: list[dict[str, Any]],
    seeded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer existing row if same email/company (re-run safe).

    Falls back to company-based dedup when email is missing so blank-contact
    rows do not get duplicated across re-runs.
    """
    by_k = _by_key(existing)
    for row in seeded:
        k = _dedup_key(row)
        if not k:
            continue
        if k not in by_k:
            by_k[k] = row
    return list(by_k.values())


def apply_blacklist_to_records(
    records: list[dict[str, Any]],
    blacklist: set[str],
) -> list[dict[str, Any]]:
    if not blacklist:
        return records
    bl = {str(x).strip().lower() for x in blacklist}
    out: list[dict[str, Any]] = []
    for r in records:
        rec = dict(r)
        k = _email_key(rec)
        if k and k in bl:
            rec["lead_status"] = LEAD_STATUS_DNC
            rec["outreach_lock"] = OUTREACH_LOCK_RELEASED
            rec["sdr_next_action"] = "Blacklisted — do not contact."
            rec["sdr_manual_allowed"] = False
            prev = str(rec.get("interaction_history") or "")
            rec["interaction_history"] = (
                prev + " | " + _log_line("Added to suppression list.")
            ).strip(" |")
        out.append(rec)
    return out


CRM_DF_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "company",
    "email",
    "linkedin",
    "phone",
    "contact_title",
    "hiring_role",
    "intent_reason",
    "intent_score",
    "intent_tier",
    "lead_status",
    "outreach_lock",
    "assigned_sdr",
    "sequence_status",
    "sequence_paused",
    "touches_sent",
    "sdr_next_action",
    "sdr_manual_allowed",
    "call_task_created",
    "interaction_history",
    "deal_status",
    "status",
    "enrichment_verified",
    "pushed_at",
)


def to_crm_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=list(CRM_DF_COLUMNS))
    df = pd.DataFrame(records)
    for col in CRM_DF_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[[c for c in CRM_DF_COLUMNS if c in df.columns]]
