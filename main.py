from __future__ import annotations

import json
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from apollo_enrichment import (
    apollo_contact_enrichment_available,
    apollo_last_error,
    apollo_quick_probe,
)
from config import (
    BRAND,
    CORPUS_CA_JOB_SHARE,
    CORPUS_US_JOB_SHARE,
    HIGH_INTENT_MAX_AGE_DAYS,
    LEAD_STATUS_AWAITING_VERIFIED_CONTACT,
    LEAD_STATUS_DNC,
    MEDIUM_INTENT_MAX_AGE_DAYS,
    MAX_EMAILS_PER_INBOX_PER_DAY,
    MAX_JOB_POSTING_AGE_DAYS,
    REPLY_INTERESTED,
    REPLY_NOT_INTERESTED,
    REPLY_UNSUBSCRIBE,
    auto_save_pipeline_to_nocodb,
    enrichment_max_companies_per_run,
    hubspot_access_token,
    hubspot_configured,
)
from crm import (
    apply_blacklist_to_records,
    apply_dispatch_to_records,
    merge_seed_with_existing,
    refresh_crm_after_replies,
    seed_crm_from_enriched,
    to_crm_dataframe,
)
from dashboard_metrics import build_dashboard
from deliverability import InboxStatus, plan_capacity
from email_engine import build_email_sequence
from role_suggestions import role_based_suggestions
from enrichment import (
    CONTACT_PENDING_STATUS,
    _looks_fabricated,
    job_board_linkedin_safe,
    lead_has_verified_contact,
    sanitize_enriched_dataframe,
    waterfall_enrichment,
)
from internal_intent import fetch_social_intent, invalidate_intent_corpus_cache
from user_geo import build_geo_hint_for_corpus, corpus_geo_cache_key
from nocodb_client import NocoDBError, find_snapshot_by_session, upsert_snapshot, append_event
from outreach import dispatch_email_internal
from pipeline import filter_outreach_ready, run_intent_stage
from reply_classification import classify_reply_text, crm_eligible
from ui_theme import (
    get_global_css,
    glass_card_end,
    glass_card_start,
    render_client_welcome,
    render_hero,
    render_stat_grid,
    render_stepper,
    section_header,
)
from walego import handoff_to_walego

from hubspot_sync import push_crm_batch


def _email_to_enriched_lead(le: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Map lowercase email → enriched lead row dict (first match) for HubSpot job context."""
    out: dict[str, dict[str, Any]] = {}
    if le is None or le.empty or "Email" not in le.columns:
        return out
    for _, row in le.iterrows():
        em = str(row.get("Email", "") or "").strip().lower()
        if em and em not in out:
            out[em] = row.to_dict()
    return out


def _build_ready_for_enrich(
    scored: pd.DataFrame | None,
    min_tier: list[str] | None,
) -> pd.DataFrame:
    """High/Medium (or selected) companies for the enrichment queue — same rules as the Scoring step."""
    if scored is None or scored.empty:
        return pd.DataFrame()
    ready = filter_outreach_ready(scored)
    if not min_tier and not ready.empty:
        return pd.DataFrame()
    if min_tier and not ready.empty:
        if "Intent tier" not in ready.columns:
            return ready
        ready = ready[ready["Intent tier"].isin(min_tier)].copy()
    return ready


def _enrichment_queue_df() -> pd.DataFrame:
    """Prefer the snapshot from Scoring; if missing (e.g. deep-linked step), rebuild from scored + sidebar tiers."""
    snap = st.session_state.get("_ready_for_enrich")
    if isinstance(snap, pd.DataFrame) and not snap.empty:
        return snap
    mt = st.session_state.get("outreach_tiers")
    if not isinstance(mt, list):
        mt = ["High", "Medium"]
    return _build_ready_for_enrich(st.session_state.get("company_scored"), mt)


# --- PAGE CONFIG ---
st.set_page_config(page_title=f"{BRAND} – Command Center", page_icon="✦", layout="wide")


def safe_toast(message: str, *, icon: str | None = None) -> None:
    """``st.toast`` that never crashes on a bad icon.

    Streamlit's ``validate_emoji`` rejects look-alike check marks (e.g. ``✓``
    U+2713) and a stray invalid icon was previously taking the whole pipeline
    down with ``StreamlitAPIException``. We catch that and retry without the
    icon so a toast can never become a crash surface.
    """
    try:
        if icon:
            st.toast(message, icon=icon)
        else:
            st.toast(message)
    except Exception:
        try:
            st.toast(message)
        except Exception:
            pass

def _make_session_id() -> str:
    """Per-browser session id so devices don't share the same NocoDB snapshot.

    Honors ``?sid=...`` in the URL so links can resume a specific session;
    otherwise generates a short random id (``sess-<8-hex>``) the first time
    this script runs in the browser.
    """
    try:
        qp = st.query_params  # type: ignore[attr-defined]
        sid_qp = qp.get("sid", "")
        if isinstance(sid_qp, list):
            sid_qp = sid_qp[0] if sid_qp else ""
        sid_qp = str(sid_qp).strip()
        if sid_qp:
            return sid_qp
    except Exception:
        pass
    return f"sess-{uuid.uuid4().hex[:8]}"


# Session defaults
if "session_id" not in st.session_state:
    st.session_state.session_id = _make_session_id()
    # Mark this as a fresh, auto-generated session so the bootstrap step
    # does NOT pull a stale snapshot tied to some other browser/device.
    st.session_state._session_is_fresh = True
if "step" not in st.session_state:
    st.session_state.step = 0
if "company_jobs" not in st.session_state:
    st.session_state.company_jobs = None
if "company_scored" not in st.session_state:
    st.session_state.company_scored = None
if "leads_enriched" not in st.session_state:
    st.session_state.leads_enriched = None
if "emails_sent_count" not in st.session_state:
    st.session_state.emails_sent_count = 0
if "walego_actions" not in st.session_state:
    st.session_state.walego_actions = 0
if "walego_accepted" not in st.session_state:
    st.session_state.walego_accepted = 0
if "walego_requests" not in st.session_state:
    st.session_state.walego_requests = 0
if "replies" not in st.session_state:
    st.session_state.replies = []
if "blacklist" not in st.session_state:
    st.session_state.blacklist = set()
if "crm_records" not in st.session_state:
    st.session_state.crm_records = []
if "outreach_simulated" not in st.session_state:
    st.session_state.outreach_simulated = False
if "replies_built" not in st.session_state:
    st.session_state.replies_built = False
if "role_suggestions" not in st.session_state:
    st.session_state.role_suggestions = None
if "nocodb_hydrated" not in st.session_state:
    st.session_state.nocodb_hydrated = False
if "session_id_in" not in st.session_state:
    st.session_state.session_id_in = st.session_state.session_id
if "assigned_sdr_label" not in st.session_state:
    st.session_state.assigned_sdr_label = "SDR Team"
if "max_job_age_days" not in st.session_state:
    st.session_state.max_job_age_days = MAX_JOB_POSTING_AGE_DAYS
if "_native_session_bootstrap_done" not in st.session_state:
    st.session_state._native_session_bootstrap_done = False
if "client_landing_dismissed" not in st.session_state:
    st.session_state.client_landing_dismissed = False
if st.session_state.get("_skip_welcome_forever"):
    st.session_state.client_landing_dismissed = True


def prev_step():
    cur = int(st.session_state.step)
    st.session_state.step = max(0, cur - 1)
    if cur == 2:
        st.session_state.leads_enriched = None
        st.session_state.role_suggestions = None


def _outreach_lead_strip_unverified_linkedin(lead: pd.Series) -> pd.Series:
    """Drop LinkedIn **person** URLs until verified; keep board job/company links."""
    out = lead.copy()
    if not bool(out.get("Enrichment verified")):
        li = str(out.get("LinkedIn") or "").strip()
        if li and not job_board_linkedin_safe(li):
            out["LinkedIn"] = ""
    return out


def _serialize_blacklist() -> list[str]:
    return sorted({str(x) for x in st.session_state.blacklist})


def _deserialize_blacklist(items: list[str]) -> None:
    st.session_state.blacklist = set(items or [])


def _scrub_crm_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip fabricated contact data from any CRM rows loaded from disk/NocoDB.

    Mirrors :func:`enrichment.sanitize_enriched_dataframe` for the CRM shape so
    a snapshot saved before the verified-only migration cannot leak
    ``@example.com`` rows into the live UI.
    """
    out: list[dict[str, Any]] = []
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        rec = dict(raw)
        name = str(rec.get("name") or "").strip()
        email = str(rec.get("email") or "").strip()
        verified = bool(rec.get("enrichment_verified"))
        li_raw = str(rec.get("linkedin") or "").strip()
        if not verified or not email or _looks_fabricated(name, email, li_raw, rec.get("phone")):
            rec["name"] = ""
            rec["email"] = ""
            rec["phone"] = ""
            rec["linkedin"] = (
                li_raw
                if job_board_linkedin_safe(li_raw) and not _looks_fabricated("", "", li_raw, "")
                else ""
            )
            rec["enrichment_verified"] = False
            rec["lead_status"] = LEAD_STATUS_AWAITING_VERIFIED_CONTACT
            rec["sequence_paused"] = True
            rec["sequence_status"] = "Paused — awaiting verified contact source"
            rec["outreach_lock"] = "Released"
            rec["sdr_manual_allowed"] = False
            rec["sdr_next_action"] = (
                "No verified contact yet. Provide a real Email / Name from a verified "
                "data source before the sequence will run."
            )
        out.append(rec)
    return out


def _payload_for_save() -> dict:
    social_df = st.session_state.get("_social_intent_snapshot")
    return {
        "snapshot_version": 2,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "company_jobs": st.session_state.company_jobs.to_dict(orient="records")
        if isinstance(st.session_state.company_jobs, pd.DataFrame)
        else None,
        "company_scored": st.session_state.company_scored.to_dict(orient="records")
        if isinstance(st.session_state.company_scored, pd.DataFrame)
        else None,
        "social_intent": social_df.to_dict(orient="records")
        if isinstance(social_df, pd.DataFrame) and not social_df.empty
        else ([] if isinstance(social_df, pd.DataFrame) else None),
        "leads_enriched": st.session_state.leads_enriched.to_dict(orient="records")
        if isinstance(st.session_state.leads_enriched, pd.DataFrame)
        else None,
        "emails_sent_count": int(st.session_state.emails_sent_count),
        "walego_actions": int(st.session_state.walego_actions),
        "walego_accepted": int(st.session_state.walego_accepted),
        "walego_requests": int(st.session_state.walego_requests),
        "replies": list(st.session_state.replies or []),
        "blacklist": _serialize_blacklist(),
        "crm_records": list(st.session_state.crm_records or []),
        "outreach_simulated": bool(st.session_state.outreach_simulated),
        "replies_built": bool(st.session_state.replies_built),
        "role_suggestions": st.session_state.role_suggestions.to_dict(orient="records")
        if isinstance(st.session_state.role_suggestions, pd.DataFrame)
        else None,
        "_ready_for_enrich": st.session_state.get("_ready_for_enrich", pd.DataFrame()).to_dict(orient="records")
        if isinstance(st.session_state.get("_ready_for_enrich"), pd.DataFrame)
        else None,
        "max_job_age_days": int(st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS)),
        "viewer_geo_key": str(st.session_state.get("_intent_geo_key_applied") or corpus_geo_cache_key(st.session_state.get("_viewer_geo"))),
        "viewer_geo": _json_friendly_geo(st.session_state.get("_viewer_geo")),
        "outreach_tiers": list(st.session_state.get("outreach_tiers") or ["High", "Medium"]),
        "assigned_sdr_label": str(st.session_state.get("assigned_sdr_label") or "SDR Team").strip(),
    }


def _hydrate_from_payload(payload: dict) -> None:
    def _df(key: str) -> pd.DataFrame | None:
        raw = payload.get(key)
        if raw is None:
            return None
        return pd.DataFrame(raw)

    st.session_state.company_jobs = _df("company_jobs")
    st.session_state.company_scored = _df("company_scored")
    st.session_state.leads_enriched = sanitize_enriched_dataframe(_df("leads_enriched"))
    st.session_state.emails_sent_count = int(payload.get("emails_sent_count") or 0)
    st.session_state.walego_actions = int(payload.get("walego_actions") or 0)
    st.session_state.walego_accepted = int(payload.get("walego_accepted") or 0)
    st.session_state.walego_requests = int(payload.get("walego_requests") or 0)
    st.session_state.replies = list(payload.get("replies") or [])
    _deserialize_blacklist(list(payload.get("blacklist") or []))
    st.session_state.crm_records = _scrub_crm_records(list(payload.get("crm_records") or []))
    st.session_state.outreach_simulated = bool(payload.get("outreach_simulated"))
    st.session_state.replies_built = bool(payload.get("replies_built"))
    rs = payload.get("role_suggestions")
    st.session_state.role_suggestions = pd.DataFrame(rs) if rs else None
    rfe = payload.get("_ready_for_enrich")
    st.session_state._ready_for_enrich = pd.DataFrame(rfe) if rfe else pd.DataFrame()
    ma = payload.get("max_job_age_days")
    if ma is not None:
        try:
            st.session_state.max_job_age_days = max(1, min(int(ma), MAX_JOB_POSTING_AGE_DAYS))
        except (TypeError, ValueError):
            pass
    if isinstance(st.session_state.company_scored, pd.DataFrame):
        st.session_state._intent_max_age_applied = int(
            st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS)
        )
    vgk = payload.get("viewer_geo_key")
    if vgk is not None:
        st.session_state._intent_geo_key_applied = str(vgk)
    vg = payload.get("viewer_geo")
    if isinstance(vg, dict) and vg:
        st.session_state._viewer_geo = vg
        st.session_state._viewer_geo_ttl = time.time() + 3600.0
    si = payload.get("social_intent")
    if si is not None:
        st.session_state._social_intent_snapshot = pd.DataFrame(si) if si else pd.DataFrame()
    ot = payload.get("outreach_tiers")
    if isinstance(ot, list) and ot:
        st.session_state.outreach_tiers = [str(x) for x in ot if str(x).strip()]
    al = payload.get("assigned_sdr_label")
    if isinstance(al, str) and al.strip():
        st.session_state.assigned_sdr_label = al.strip()


def _viewer_geo_maybe_refresh() -> None:
    """Throttle IP geolocation lookups (ip-api.com) to once per hour per session."""
    now = time.time()
    ttl = float(st.session_state.get("_viewer_geo_ttl") or 0)
    if ttl > now and isinstance(st.session_state.get("_viewer_geo"), dict):
        return
    st.session_state._viewer_geo = build_geo_hint_for_corpus()
    st.session_state._viewer_geo_ttl = now + 3600.0


def _prefetch_intent_worker(max_age: int, geo_hint: dict[str, Any] | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Runs off the main Streamlit thread — must not call any ``st.*`` APIs."""
    return run_intent_stage(max_job_age_days=max_age, geo_hint=geo_hint, on_jobs_stream=None)


def _maybe_start_client_intent_prefetch() -> None:
    if st.session_state.get("client_landing_dismissed"):
        return
    if st.session_state.get("_intent_prefetch_submitted"):
        return
    if isinstance(st.session_state.get("company_scored"), pd.DataFrame) and not st.session_state.company_scored.empty:
        st.session_state._intent_prefetch_submitted = True
        return
    max_age = max(1, min(int(st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS)), MAX_JOB_POSTING_AGE_DAYS))
    gh = st.session_state.get("_viewer_geo")
    gh = gh if isinstance(gh, dict) else None
    ex = st.session_state.get("_prefetch_executor")
    if ex is None:
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hq_welcome")
        st.session_state._prefetch_executor = ex
    fut = ex.submit(_prefetch_intent_worker, max_age, gh)
    st.session_state._intent_prefetch_future = fut
    st.session_state._intent_prefetch_submitted = True


def _try_merge_prefetch_future() -> bool:
    fut = st.session_state.get("_intent_prefetch_future")
    if fut is None or not fut.done():
        return False
    try:
        jobs, scored = fut.result(timeout=0)
    except Exception as exc:
        st.session_state._intent_prefetch_future = None
        st.session_state._intent_prefetch_error = str(exc)
        return False
    st.session_state._intent_prefetch_future = None
    st.session_state.company_jobs = jobs
    st.session_state.company_scored = scored
    st.session_state._intent_max_age_applied = max(
        1, min(int(st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS)), MAX_JOB_POSTING_AGE_DAYS)
    )
    st.session_state._intent_geo_key_applied = corpus_geo_cache_key(st.session_state.get("_viewer_geo"))
    st.session_state._intent_prefetch_ready = True
    st.session_state.pop("_intent_prefetch_error", None)
    return True


def _drain_prefetch_future_blocking() -> None:
    """If user leaves the welcome screen while the worker is still running, block briefly once."""
    fut = st.session_state.get("_intent_prefetch_future")
    if fut is None:
        return
    if fut.done():
        _try_merge_prefetch_future()
        return
    with st.spinner("Finishing the background intent snapshot…"):
        try:
            jobs, scored = fut.result(timeout=300)
        except Exception:
            st.session_state._intent_prefetch_future = None
            return
    st.session_state._intent_prefetch_future = None
    st.session_state.company_jobs = jobs
    st.session_state.company_scored = scored
    st.session_state._intent_max_age_applied = max(
        1, min(int(st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS)), MAX_JOB_POSTING_AGE_DAYS)
    )
    st.session_state._intent_geo_key_applied = corpus_geo_cache_key(st.session_state.get("_viewer_geo"))
    st.session_state._intent_prefetch_ready = True
    st.session_state.pop("_intent_prefetch_error", None)


@st.fragment(run_every=timedelta(seconds=1.0))
def _client_welcome_background_fragment() -> None:
    """Polls prefetch completion + animates progress while the welcome screen is visible.

    Streamlit logs a benign ``fragment ... does not exist anymore`` line when a
    polling tick fires after a parent ``st.rerun()`` removed the fragment.
    Slower cadence (1s) + an early bail-out as soon as the landing page is
    dismissed or the snapshot is ready keeps that log noise low without
    sacrificing the “loading…” feedback.
    """
    if st.session_state.get("client_landing_dismissed"):
        return
    merged = _try_merge_prefetch_future()
    if merged and not st.session_state.get("_prefetch_ready_toast_shown"):
        safe_toast("Intent snapshot is ready — enter the command center when you like.", icon="✨")
        st.session_state._prefetch_ready_toast_shown = True
    prog_slot = st.empty()
    fut = st.session_state.get("_intent_prefetch_future")
    if st.session_state.get("_intent_prefetch_ready"):
        prog_slot.progress(1.0, text="Intent snapshot ready")
        return
    if fut is not None and not fut.done():
        pulse = 0.18 + 0.72 * (0.5 + 0.5 * math.sin(time.monotonic() * 2.05))
        prog_slot.progress(min(0.94, pulse), text="Fetching listings & scores in the background…")
    elif st.session_state.get("_intent_prefetch_error"):
        prog_slot.warning("Background fetch reported an issue — we will retry after you enter.")
    elif st.session_state.get("_intent_prefetch_submitted"):
        prog_slot.progress(0.12, text="Starting background pull…")
    else:
        prog_slot.progress(0.05, text="Preparing background pull…")


def _json_friendly_geo(geo: Any) -> dict[str, Any] | None:
    """Strip viewer geo to JSON-serializable primitives for NocoDB payload."""
    if not isinstance(geo, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in geo.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)] = v
        elif isinstance(v, (list, tuple)):
            out[str(k)] = [
                x if isinstance(x, (str, int, float, bool)) or x is None else str(x) for x in v
            ]
        else:
            out[str(k)] = str(v)
    return out


def _save_to_nocodb() -> None:
    payload = _payload_for_save()
    upsert_snapshot(st.session_state.session_id, int(st.session_state.step), payload)
    append_event("pipeline_save", {"session_id": st.session_state.session_id, "step": st.session_state.step})


def _maybe_auto_save_nocodb(reason: str) -> None:
    """Best-effort persist the pipeline snapshot to NocoDB.

    Auto-save must never break the user-visible flow — any error (TypeError
    from a stray non-serializable value, NocoDBError from a misconfigured
    table, transient network blip) is swallowed and surfaced as a quiet
    in-app warning instead of crashing the page.
    """
    if not auto_save_pipeline_to_nocodb():
        return
    try:
        upsert_snapshot(st.session_state.session_id, int(st.session_state.step), _payload_for_save())
    except NocoDBError as exc:
        st.warning(f"Auto-save to NocoDB failed ({reason}): {exc}")
        return
    except Exception as exc:
        st.warning(f"Auto-save to NocoDB skipped ({reason}): {exc}")
        return
    try:
        append_event(
            "pipeline_auto_save",
            {"session_id": st.session_state.session_id, "step": st.session_state.step, "reason": reason},
        )
    except NocoDBError:
        pass
    except Exception:
        pass


def _hydrate_from_nocodb() -> None:
    if st.session_state.nocodb_hydrated:
        return
    # Fresh auto-generated sessions have nothing to hydrate from and must NOT
    # accidentally inherit another device's snapshot via the legacy "default"
    # session id. Only hydrate when the user explicitly asked for a session id.
    if st.session_state.get("_session_is_fresh"):
        st.session_state.nocodb_hydrated = True
        return
    try:
        rid, row = find_snapshot_by_session(st.session_state.session_id)
    except NocoDBError:
        st.session_state.nocodb_hydrated = True
        return
    if not rid or not row:
        st.session_state.nocodb_hydrated = True
        return
    raw = row.get("payload_json") or row.get("Payload_json") or row.get("payload")
    if not raw:
        st.session_state.nocodb_hydrated = True
        return
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        st.session_state.nocodb_hydrated = True
        return
    step_val = row.get("step") or row.get("Step")
    if step_val is not None:
        try:
            st.session_state.step = int(step_val)
        except (TypeError, ValueError):
            pass
    _hydrate_from_payload(payload if isinstance(payload, dict) else {})
    st.session_state.nocodb_hydrated = True


def _ensure_intent():
    _drain_prefetch_future_blocking()
    max_age = int(st.session_state.get("max_job_age_days", MAX_JOB_POSTING_AGE_DAYS))
    max_age = max(1, min(max_age, MAX_JOB_POSTING_AGE_DAYS))
    cached = st.session_state.get("_intent_max_age_applied")
    geo_hint = st.session_state.get("_viewer_geo")
    if not isinstance(geo_hint, dict):
        geo_hint = None
    geo_key = corpus_geo_cache_key(geo_hint)
    intent_refreshed = False
    cached_geo = st.session_state.get("_intent_geo_key_applied")
    if (
        cached_geo is None
        and isinstance(st.session_state.company_scored, pd.DataFrame)
        and not st.session_state.company_scored.empty
    ):
        st.session_state._intent_geo_key_applied = geo_key
        cached_geo = geo_key
    if (
        st.session_state.company_scored is None
        or cached != max_age
        or cached_geo != geo_key
    ):
        stream_info_slot = st.empty()
        stream_table_slot = st.empty()
        prog = st.progress(0, text="Intent pipeline…")

        def _on_jobs_stream(partial_jobs: pd.DataFrame) -> None:
            if partial_jobs is None or partial_jobs.empty:
                return
            live_df = partial_jobs.copy()
            if "Posting date" in live_df.columns:
                live_df = live_df.sort_values("Posting date", ascending=False)
            n = len(live_df)
            stream_info_slot.caption(
                f"Live fetch: {n} rows so far — additional rows may still stream in."
            )
            stream_table_slot.dataframe(
                live_df.head(120),
                width="stretch",
                hide_index=True,
            )
            prog.progress(min(92, 15 + min(n, 75)), text=f"Received {n} job rows…")

        pipe_ref: Any = None
        try:
            with st.status("Intent pipeline", expanded=True) as pipe:
                pipe_ref = pipe
                pipe.update(
                    label="Running intent pipeline (live boards + LLM fallback, then scoring)…",
                    state="running",
                )
                prog.progress(12, text="Fetching & scoring…")
                jobs, scored = run_intent_stage(
                    max_job_age_days=max_age,
                    geo_hint=geo_hint,
                    on_jobs_stream=_on_jobs_stream,
                )
                st.session_state.company_jobs = jobs
                st.session_state.company_scored = scored
                st.session_state._intent_max_age_applied = max_age
                st.session_state._intent_geo_key_applied = geo_key
                nj = len(jobs) if isinstance(jobs, pd.DataFrame) else 0
                nc = len(scored) if isinstance(scored, pd.DataFrame) else 0
                prog.progress(100, text="Complete")
                # Avoid custom label on state="complete" — overlaps with Streamlit's completion chrome.
                pipe.update(state="complete")
                safe_toast(f"Intent ready — {nj} job postings, {nc} companies scored.", icon="✅")
                intent_refreshed = True
                try:
                    st.session_state._social_intent_snapshot = fetch_social_intent(geo_hint=geo_hint)
                except Exception:
                    st.session_state._social_intent_snapshot = pd.DataFrame()
        except Exception as exc:
            if pipe_ref is not None:
                pipe_ref.update(
                    label=f"Intent failed: {exc}",
                    state="error",
                )
            st.error(
                "Intent stage failed. Check your **ANTHROPIC_API_KEY** / **OPENAI_API_KEY** and "
                "`LLM_PROVIDER_ORDER` in `.env` or Streamlit secrets. For live Indeed/LinkedIn rows, "
                "install **`python-jobspy`** (not the PyPI package named `jobspy`). "
                f"Details: {exc}"
            )
            st.session_state.company_jobs = pd.DataFrame()
            st.session_state.company_scored = pd.DataFrame()
        finally:
            prog.empty()
            stream_info_slot.empty()
            stream_table_slot.empty()
        if intent_refreshed:
            _maybe_auto_save_nocodb("intent_refresh")

    if not intent_refreshed:
        sc2 = st.session_state.get("company_scored")
        if isinstance(sc2, pd.DataFrame) and not sc2.empty:
            si = st.session_state.get("_social_intent_snapshot")
            if not isinstance(si, pd.DataFrame) or si.empty:
                try:
                    st.session_state._social_intent_snapshot = fetch_social_intent(geo_hint=geo_hint)
                except Exception:
                    st.session_state._social_intent_snapshot = pd.DataFrame()


st.markdown(get_global_css(), unsafe_allow_html=True)

# Native Streamlit boot: first paint only (avoids flashing on every rerun).
# Use a spinner only — collapsed st.status + state="complete" can render overlapping labels
# (built-in check / “Complete” vs custom text) on some Streamlit versions.
if not st.session_state._native_session_bootstrap_done:
    with st.spinner("Loading workspace — session snapshot and region…"):
        _hydrate_from_nocodb()
        _viewer_geo_maybe_refresh()
    st.session_state._native_session_bootstrap_done = True
else:
    _hydrate_from_nocodb()
    _viewer_geo_maybe_refresh()

# Defensive sanitize: even sessions that already had pre-migration values cached
# in-memory get scrubbed every rerun. Cheap (O(n) over a small frame).
if isinstance(st.session_state.leads_enriched, pd.DataFrame):
    st.session_state.leads_enriched = sanitize_enriched_dataframe(
        st.session_state.leads_enriched
    )
if st.session_state.crm_records:
    st.session_state.crm_records = _scrub_crm_records(st.session_state.crm_records)

# --- SIDEBAR ---
with st.sidebar:
    st.markdown(
        """
        <div style="padding:0.1rem 0 0.9rem;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:1rem;">
        <span style="font-size:0.62rem;letter-spacing:0.22em;text-transform:uppercase;color:#a78bfa;">Session</span><br/>
        <span style="font-size:1.15rem;font-weight:700;background:linear-gradient(90deg,#fff,#c4b5fd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">hirequity</span>
        <p style="margin:0.35rem 0 0;font-size:0.78rem;color:#71717a !important;">In-house · Claude API · NocoDB · verified contacts only</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input("Session id", key="session_id_in")
    st.text_input(
        "Assigned SDR (CRM visibility)",
        key="assigned_sdr_label",
        help="Shown on every lead after enrich. Automation still holds the outreach lock until release rules fire.",
    )

    def _apply_session():
        new_sid = (st.session_state.session_id_in or "").strip()
        if not new_sid:
            new_sid = _make_session_id()
        st.session_state.session_id = new_sid
        # User explicitly typed/loaded this id → allow NocoDB hydration to run.
        st.session_state._session_is_fresh = False
        st.session_state.nocodb_hydrated = False
        st.session_state._native_session_bootstrap_done = False
        st.session_state.client_landing_dismissed = False
        st.session_state._intent_prefetch_submitted = False
        st.session_state.pop("_intent_prefetch_future", None)
        st.session_state.pop("_intent_prefetch_ready", None)
        st.session_state.pop("_prefetch_ready_toast_shown", None)
        st.session_state.pop("_intent_prefetch_error", None)
        st.session_state.pop("_intent_geo_key_applied", None)
        st.session_state.pop("_social_intent_snapshot", None)
        st.session_state.company_jobs = None
        st.session_state.company_scored = None
        st.session_state.leads_enriched = None
        st.session_state.replies = []
        st.session_state.blacklist = set()
        st.session_state.crm_records = []
        st.session_state.role_suggestions = None
        st.session_state.replies_built = False
        st.session_state.outreach_simulated = False
        st.session_state.step = 0

    st.button("Apply session + reload from NocoDB", on_click=_apply_session, width="stretch")

    st.text_input("Destination email (optional)", placeholder="you@company.com", key="test_email_in")
    st.slider(
        "Max job posting age (days)",
        min_value=1,
        max_value=MAX_JOB_POSTING_AGE_DAYS,
        key="max_job_age_days",
        help=f"Listings older than this many days are dropped (hard cap {MAX_JOB_POSTING_AGE_DAYS} days ≈ 3 weeks).",
    )
    st.multiselect(
        "Outreach tiers",
        ["High", "Medium"],
        default=["High", "Medium"],
        key="outreach_tiers",
        help="Companies outside these tiers are hidden from enrichment and downstream outreach.",
    )
    min_tier = list(st.session_state.get("outreach_tiers") or ["High", "Medium"])
    vg = st.session_state.get("_viewer_geo")
    if isinstance(vg, dict) and vg.get("summary"):
        st.caption(vg["summary"])
    st.caption(
        f"Country priority target: ~{int(round(CORPUS_CA_JOB_SHARE * 100))}% Canada / {int(round(CORPUS_US_JOB_SHARE * 100))}% US."
    )
    if st.session_state.get("client_landing_dismissed"):
        if st.button("Show client welcome", width="stretch"):
            st.session_state.client_landing_dismissed = False
            st.session_state._intent_prefetch_submitted = False
            st.session_state.pop("_intent_prefetch_future", None)
            st.session_state.pop("_intent_prefetch_ready", None)
            st.session_state.pop("_prefetch_ready_toast_shown", None)
            st.session_state.pop("_intent_prefetch_error", None)
            st.rerun()

    st.markdown("---")
    if apollo_contact_enrichment_available():
        st.success("Apollo: key detected", icon="🟢")
    else:
        st.warning("Apollo: no key (set APOLLO_API_KEY)", icon="🟡")
    if st.button("Test Apollo connectivity", width="stretch"):
        ok, msg = apollo_quick_probe()
        if ok:
            st.success(msg)
        else:
            st.error(msg)
    le_now = st.session_state.get("leads_enriched")
    if isinstance(le_now, pd.DataFrame) and not le_now.empty and "Enrichment verified" in le_now.columns:
        n_ok = int(le_now["Enrichment verified"].astype(bool).sum())
        n_tot = len(le_now)
        st.caption(f"Enriched rows verified by Apollo: **{n_ok} / {n_tot}**")
    last_err = apollo_last_error()
    if last_err:
        st.caption(f"Last Apollo error: {last_err[:180]}")

    if st.button("Save pipeline to NocoDB", width="stretch"):
        try:
            _save_to_nocodb()
            st.success("Saved snapshot to NocoDB.")
        except NocoDBError as exc:
            st.error(str(exc))

    if st.button(
        "Clear stale enriched contacts",
        width="stretch",
        help="Wipes any cached enrichment/CRM rows from before the verified-only policy. "
        "Use this if you still see placeholder names or example.com emails.",
    ):
        st.session_state.leads_enriched = None
        st.session_state.crm_records = []
        st.session_state.role_suggestions = None
        st.session_state.outreach_simulated = False
        st.session_state.emails_sent_count = 0
        st.session_state.walego_actions = 0
        st.session_state.walego_accepted = 0
        st.session_state.walego_requests = 0
        safe_toast("Cleared. Re-run Enrichment for fresh, verified-only rows.", icon="🧹")
        st.rerun()

    if st.button("Reset pipeline", width="stretch"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.session_state.step = 0
        st.session_state.blacklist = set()
        st.session_state.outreach_simulated = False
        st.session_state.replies_built = False
        new_sid = _make_session_id()
        st.session_state.session_id = new_sid
        st.session_state.session_id_in = new_sid
        st.session_state._session_is_fresh = True
        st.session_state.nocodb_hydrated = False
        st.session_state._native_session_bootstrap_done = False
        st.session_state.max_job_age_days = MAX_JOB_POSTING_AGE_DAYS
        invalidate_intent_corpus_cache()
        st.rerun()

    if st.button(
        "Force fresh live fetch",
        width="stretch",
        help="Bypass the in-memory job-board cache and re-pull from Indeed / LinkedIn now. "
        "Use when multiple devices appear to see the same listings.",
    ):
        invalidate_intent_corpus_cache()
        st.session_state.company_jobs = None
        st.session_state.company_scored = None
        st.session_state._intent_prefetch_submitted = False
        st.session_state.pop("_intent_prefetch_future", None)
        st.session_state.pop("_intent_prefetch_ready", None)
        st.session_state.pop("_prefetch_ready_toast_shown", None)
        st.session_state.pop("_intent_prefetch_error", None)
        safe_toast("Live job-board cache cleared — next fetch will hit Indeed / LinkedIn directly.", icon="🔄")
        st.rerun()

# --- Client welcome (first screen): animated landing + background intent prefetch ---
if not st.session_state.get("client_landing_dismissed"):
    st.markdown(render_client_welcome(BRAND), unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:#a1a1aa;font-size:0.95rem;margin:-0.5rem 0 1.25rem;max-width:520px;margin-left:auto;margin-right:auto;'>"
        "Live listings and scores load in the background while you read — by the time you enter, "
        "the first batch is often already on the board.</p>",
        unsafe_allow_html=True,
    )
    # Buttons rendered FIRST and unconditionally so they never get hidden by the
    # progress fragment's tick (some Streamlit Cloud workers used to flash them).
    c_enter, c_skip, c_hint = st.columns([1.05, 1.15, 1.8])
    with c_enter:
        if st.button("Enter command center", type="primary", width="stretch", key="hq_landing_enter"):
            st.session_state.client_landing_dismissed = True
            st.rerun()
    with c_skip:
        if st.button("Skip welcome next time", width="stretch", key="hq_landing_skip_forever"):
            st.session_state._skip_welcome_forever = True
            st.session_state.client_landing_dismissed = True
            st.rerun()
    with c_hint:
        st.caption("Stay a few seconds for the shimmer — your pipeline is already spinning up.")
    _maybe_start_client_intent_prefetch()
    _client_welcome_background_fragment()
    st.stop()

_ensure_intent()
jobs = st.session_state.company_jobs
scored = st.session_state.company_scored

# --- HERO + STEPPER ---
st.markdown(render_hero(BRAND), unsafe_allow_html=True)
st.markdown(render_stepper(st.session_state.step), unsafe_allow_html=True)

# --- STEP 0: INTENT ---
if st.session_state.step == 0:
    st.markdown(
        section_header(
            "Intent engine",
            "Live job-board ingestion (Indeed/LinkedIn) with model fallback, then scored like a real pipeline. "
            f"Job postings older than the sidebar “max age” (up to {MAX_JOB_POSTING_AGE_DAYS} days) are excluded. "
            f"Tiering uses recency: High ≤ {HIGH_INTENT_MAX_AGE_DAYS} days, Medium ≤ {MEDIUM_INTENT_MAX_AGE_DAYS} days. "
            f"Listings target ~{int(round(CORPUS_CA_JOB_SHARE * 100))}% Canada / {int(round(CORPUS_US_JOB_SHARE * 100))}% US.",
        ),
        unsafe_allow_html=True,
    )
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(
            glass_card_start("Job postings")
            + f"<p>Filtered: Sales Rep, AE, SDR, BDR, and related GTM roles. Posting age ≤ {int(st.session_state.get('max_job_age_days', MAX_JOB_POSTING_AGE_DAYS))} days (cap {MAX_JOB_POSTING_AGE_DAYS}d). "
            + f"Country mix target: ~{int(round(CORPUS_CA_JOB_SHARE * 100))}% CA / {int(round(CORPUS_US_JOB_SHARE * 100))}% US.</p>"
            + glass_card_end(),
            unsafe_allow_html=True,
        )
        st.dataframe(jobs if jobs is not None and not jobs.empty else pd.DataFrame(), width="stretch", hide_index=True)
        st.caption(
            f"Jobs fetched this run: {len(jobs) if isinstance(jobs, pd.DataFrame) else 0}"
        )
        if isinstance(jobs, pd.DataFrame) and jobs.empty:
            st.info(
                "No rows yet — common causes: **(1)** Wrong dependency: the PyPI package `jobspy` is not the board "
                "scraper; this app needs **`python-jobspy`** (Python **3.10+**). Reinstall from `requirements.txt`. "
                "**(2)** Live boards rate-limited / unavailable — try again in a few minutes. "
                "**(3)** Click **Refresh intent (live job boards)** to retry."
            )
    with d2:
        st.markdown(
            glass_card_start("Company intelligence")
            + "<p>Signals: role age, &gt;14d urgency, multi-role hiring, social mentions.</p>"
            + glass_card_end(),
            unsafe_allow_html=True,
        )
        st.dataframe(scored if scored is not None and not scored.empty else pd.DataFrame(), width="stretch", hide_index=True)
    social_snap = st.session_state.get("_social_intent_snapshot")
    has_fetched = (
        (isinstance(jobs, pd.DataFrame) and not jobs.empty)
        or (isinstance(scored, pd.DataFrame) and not scored.empty)
        or (isinstance(social_snap, pd.DataFrame) and not social_snap.empty)
    )
    if st.button(
        "Save fetched data to NocoDB",
        width="stretch",
        key="hq_save_fetch_nocodb",
        disabled=not has_fetched,
        help="Upserts this session’s snapshot (job pull, company scores, social intent, geo/tiers) into your pipeline table — same payload as sidebar “Save pipeline to NocoDB”.",
    ):
        try:
            _save_to_nocodb()
            try:
                append_event("pipeline_fetch_save", {"session_id": st.session_state.session_id})
            except NocoDBError:
                pass
            st.success("Fetched data saved to your NocoDB pipeline table.")
        except NocoDBError as exc:
            st.error(str(exc))
    st.caption("Requires `NOCODB_*` in `.env` or Streamlit secrets; uses `NOCODB_PIPELINE_TABLE_ID`.")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.button("Back", disabled=True, width="stretch")
    with c2:
        if st.button("Continue to scoring →", type="primary", width="stretch"):
            st.session_state.step = 1
            st.rerun()
    if st.button("Refresh intent (live job boards)", width="stretch"):
        invalidate_intent_corpus_cache()
        st.session_state.company_jobs = None
        st.session_state.company_scored = None
        safe_toast("Refreshing intent — watch the status block above.", icon="🔄")
        _ensure_intent()
        st.rerun()

# --- STEP 1: SCORING ---
elif st.session_state.step == 1:
    st.markdown(
        section_header(
            "Scoring & gate",
            "Only High and Medium intent earn touches. Low intent is intentionally deprioritized.",
        ),
        unsafe_allow_html=True,
    )
    if scored is None or scored.empty:
        st.warning("No companies in intent pipeline.")
    else:
        st.dataframe(scored, width="stretch", hide_index=True)
    ready = _build_ready_for_enrich(scored, min_tier)
    m1, m2 = st.columns(2)
    with m1:
        st.metric("Qualified for enrichment", len(ready))
    with m2:
        st.metric("Intent focus", "Quality over volume")
    st.session_state._ready_for_enrich = ready
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, width="stretch")
    with c2:
        if st.button("Run enrichment →", type="primary", width="stretch", key="hq_goto_enrich"):
            st.session_state.step = 2
            st.session_state._ready_for_enrich = ready
            st.rerun()

# --- STEP 2: ENRICHMENT ---
elif st.session_state.step == 2:
    _enrich_help = (
        "Job-board signals (titles, URLs) always come from the live scrape. "
        f"**Apollo is enabled** — up to **{enrichment_max_companies_per_run()}** companies per run get "
        "Name / Email / decision-maker Title / LinkedIn / phone (when Apollo returns them) via search + "
        "``people/match``; this uses your Apollo credits."
        if apollo_contact_enrichment_available()
        else (
            "Job-board signals (titles, URLs) always come from the live scrape. "
            "Set **APOLLO_API_KEY** (Apollo master API key) in environment or Streamlit secrets to "
            f"auto-enrich up to **{enrichment_max_companies_per_run()}** companies per run with verified "
            "sales contacts. Person fields stay empty until that key is present."
        )
    )
    st.markdown(
        section_header("Enrichment", _enrich_help),
        unsafe_allow_html=True,
    )
    ready = _enrichment_queue_df()
    st.session_state._ready_for_enrich = ready
    st.markdown("<div class='hq-glass'>", unsafe_allow_html=True)
    if ready.empty:
        st.warning(
            "No companies match **Outreach tiers** as High/Medium (or your selection is empty). "
            "Open the sidebar, include the tiers you need, then go back to **Scoring** so the queue refreshes."
        )
    else:
        st.caption(f"{len(ready)} compan{'y' if len(ready) == 1 else 'ies'} in the enrichment queue.")
    if st.session_state.leads_enriched is None:
        if st.button(
            "Execute enrichment",
            type="primary",
            width="stretch",
            key="hq_execute_enrich",
            disabled=ready.empty,
        ):
            ready_run = _enrichment_queue_df()
            st.session_state._ready_for_enrich = ready_run
            if ready_run.empty:
                st.error(
                    "No qualified companies to enrich. Adjust **Outreach tiers** in the sidebar or return to "
                    "**Intent** for more hiring signals, then **Scoring** again."
                )
            else:
                with st.status("Enrichment", expanded=True) as enrich_status:
                    enrich_status.update(
                        label=f"Building job-signal rows for {len(ready_run)} companies…",
                        state="running",
                    )

                    def _apollo_prog(cur: int, tot: int, co: str) -> None:
                        enrich_status.update(
                            label=f"Apollo contact lookup {cur}/{tot} — {co[:52]}",
                            state="running",
                        )

                    try:
                        st.session_state.leads_enriched = waterfall_enrichment(
                            ready_run,
                            on_progress=_apollo_prog,
                        )
                    except Exception as exc:
                        enrich_status.update(label=f"Enrichment failed: {exc}", state="error")
                        st.error(f"Enrichment failed. Details: {exc}")
                    else:
                        n_en = len(st.session_state.leads_enriched)
                        n_ok = 0
                        le = st.session_state.leads_enriched
                        if isinstance(le, pd.DataFrame) and not le.empty and "Enrichment verified" in le.columns:
                            n_ok = int(le["Enrichment verified"].astype(bool).sum())
                        enrich_status.update(state="complete")
                        if apollo_contact_enrichment_available():
                            safe_toast(
                                f"Enrichment complete — {n_en} compan(y/ies), {n_ok} with verified Apollo contact.",
                                icon="✅",
                            )
                        else:
                            safe_toast(
                                f"Enrichment complete — {n_en} compan(y/ies). Add APOLLO_API_KEY for person contacts.",
                                icon="✅",
                            )
                        _maybe_auto_save_nocodb("enrichment")
                        st.rerun()
    else:
        st.success("Enrichment ready — review the table below.")
        st.dataframe(st.session_state.leads_enriched, width="stretch", hide_index=True)
        if apollo_contact_enrichment_available():
            st.info(
                "**Hiring role** is still the open posting line from job boards. **Title** shows the "
                "decision-maker role from Apollo when a match was found. Dispatch requires "
                "**Enrichment verified** + **Email** (Apollo fills these on hits). "
                f"Only the first **{enrichment_max_companies_per_run()}** rows per run call Apollo — re-run "
                "or raise **ENRICHMENT_MAX_COMPANIES** for larger batches."
            )
        else:
            st.info(
                "Add **APOLLO_API_KEY** to enable automatic Name / Email / phone / LinkedIn for sales "
                f"contacts (up to **{enrichment_max_companies_per_run()}** companies per enrichment run). "
                "Until then, only job-board columns are populated."
            )
        if st.button(
            "Generate smart role-based email suggestions",
            width="stretch",
            key="hq_role_suggestions",
        ):
            st.session_state.role_suggestions = role_based_suggestions(st.session_state.leads_enriched)
            st.rerun()
        if st.session_state.role_suggestions is not None:
            st.markdown("**Smart personalization suggestions (by enriched role)**")
            st.dataframe(st.session_state.role_suggestions, width="stretch", hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, width="stretch")
    with c2:
        if st.session_state.leads_enriched is not None and st.button(
            "Push to CRM (queued) + Outreach →", type="primary", width="stretch"
        ):
            le2 = st.session_state.leads_enriched
            assigned = str(st.session_state.get("assigned_sdr_label") or "SDR Team").strip() or "SDR Team"
            seeded = seed_crm_from_enriched(le2, assigned, st.session_state.blacklist)
            st.session_state.crm_records = merge_seed_with_existing(st.session_state.crm_records, seeded)
            try:
                append_event("crm_queued", {"records": len(st.session_state.crm_records)})
            except NocoDBError:
                pass
            st.session_state.step = 3
            st.rerun()

# --- STEP 3: OUTREACH ---
elif st.session_state.step == 3:
    st.markdown(
        section_header(
            "Outreach",
            "Sequences are built from deterministic templates so they render instantly and never "
            "fabricate a recipient name. Dispatch only runs for leads with a verified contact "
            "(**Enrichment verified** + non-empty Email). Everything else is held with status "
            "**Awaiting verified contact** for SDR review.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    if le is None or le.empty:
        st.warning("Complete enrichment first.")
        st.button("← Back", on_click=prev_step, width="stretch")
    else:
        ib = InboxStatus(inbox_id="inbox-1", sent_today=st.session_state.emails_sent_count)
        st.markdown(
            f"<div class='hq-fade' style='margin-bottom:0.75rem;'>Deliverability planning: {escape(plan_capacity(ib.sent_today))} · cap {MAX_EMAILS_PER_INBOX_PER_DAY}/inbox/day.</div>",
            unsafe_allow_html=True,
        )
        unverified_total = int((~le.apply(lead_has_verified_contact, axis=1)).sum()) if not le.empty else 0
        verified_total = len(le) - unverified_total if not le.empty else 0
        if unverified_total:
            if apollo_contact_enrichment_available():
                hint = (
                    f"{unverified_total} lead(s) have no verified contact. Apollo is enabled but "
                    "either it didn't have a match for these companies, or **enrichment was run "
                    "before the key was set**. Go back to **Enrichment**, click **Clear stale "
                    "enriched contacts** in the sidebar, then **Execute enrichment** again."
                )
            else:
                hint = (
                    f"{unverified_total} lead(s) have no verified contact and will be **held** "
                    "from dispatch. Plug in a verified provider (Apollo / Hunter / ZoomInfo) "
                    "or import a CSV with confirmed contacts before they will be sent."
                )
            st.warning(hint)
        st.caption(
            f"Dispatch will run for **{verified_total}** verified lead(s). "
            "Drafts are still rendered below for every row so SDRs can review the messaging."
        )

        if st.button(
            "Log outreach dispatch to NocoDB",
            type="primary",
            width="stretch",
            disabled=verified_total == 0,
        ) or st.session_state.outreach_simulated:
            st.session_state.outreach_simulated = True
            if st.session_state.emails_sent_count == 0 and st.session_state.walego_actions == 0:
                if not st.session_state.crm_records:
                    assigned = str(st.session_state.get("assigned_sdr_label") or "SDR Team").strip() or "SDR Team"
                    st.session_state.crm_records = seed_crm_from_enriched(le, assigned, st.session_state.blacklist)
                sent_count = 0
                w_req = 0
                touches_by_email: dict[str, int] = {}
                skipped_high_intent: list[str] = []
                skipped_unverified: list[str] = []
                for _, raw_lead in le.iterrows():
                    lead = _outreach_lead_strip_unverified_linkedin(raw_lead)
                    em_addr = str(lead.get("Email", "") or "").strip()
                    if not lead_has_verified_contact(lead):
                        skipped_unverified.append(str(lead.get("Company", "")) or "(unknown)")
                        continue
                    if em_addr in st.session_state.blacklist:
                        continue
                    em_key = em_addr.lower()
                    rec = next(
                        (
                            x
                            for x in (st.session_state.crm_records or [])
                            if str(x.get("email", "")).strip().lower() == em_key
                        ),
                        None,
                    )
                    if rec and rec.get("sequence_paused"):
                        skipped_high_intent.append(em_addr or em_key)
                        continue
                    seq = build_email_sequence(lead)
                    lead_sent = 0
                    for em in seq:
                        ok, msg = dispatch_email_internal(em_addr, em["subject"], em["body"])
                        if ok:
                            lead_sent += 1
                        else:
                            st.warning(f"Dispatch log failed for {em_addr}: {msg}")
                            break
                    touches_by_email[em_key] = lead_sent
                    sent_count += lead_sent
                    w_req += 1
                st.session_state.crm_records = apply_dispatch_to_records(
                    list(st.session_state.crm_records or []),
                    touches_by_email,
                )
                st.session_state.walego_actions = w_req
                st.session_state.walego_requests = w_req
                st.session_state.walego_accepted = 0
                st.session_state.emails_sent_count = sent_count
                if skipped_unverified:
                    sample = ", ".join(skipped_unverified[:8])
                    suffix = "…" if len(skipped_unverified) > 8 else ""
                    st.info(
                        f"{len(skipped_unverified)} lead(s) skipped — awaiting verified "
                        f"contact: {sample}{suffix}"
                    )
                if skipped_high_intent:
                    st.info(
                        "High-intent hold: sequence paused until SDR review for: "
                        + ", ".join(skipped_high_intent[:12])
                        + ("…" if len(skipped_high_intent) > 12 else "")
                    )
        for _, raw_lead in le.iterrows():
            lead = _outreach_lead_strip_unverified_linkedin(raw_lead)
            if str(lead.get("Email", "")) in st.session_state.blacklist:
                continue
            company_label = escape(str(lead.get("Company", "")))
            name_val = str(lead.get("Name", "") or "").strip()
            verified = lead_has_verified_contact(lead)
            if name_val and verified:
                header = escape(name_val)
                meta = f"{company_label} · Email-first sequence (max 3) + Walego handoff"
            else:
                header = company_label
                meta = (
                    f"{company_label} · <span style='color:#fbbf24;'>Awaiting verified contact</span> "
                    "· sequence rendered for SDR preview only"
                )
            seq = build_email_sequence(lead)
            blocks = [
                '<div class="hq-lead">',
                f"<h4>{header}</h4><div class=\"meta\">{meta}</div>",
            ]
            for em in seq:
                blocks.append(
                    f'<div class="email-draft-box"><b>Touch {em["step"]}</b> · {escape(em["subject"])}<br><br>{escape(em["body"])}</div>'
                )
            if verified:
                blocks.append(
                    f'<p class="meta">Walego JSON payload (execution layer)</p><pre style="font-size:0.75rem;opacity:0.9;">{escape(handoff_to_walego(lead))}</pre>'
                )
                blocks.append("<p class=\"meta\">Walego handoff generated (in-house payload).</p></div>")
            else:
                blocks.append(
                    "<p class=\"meta\">Walego handoff withheld until a verified contact is attached.</p></div>"
                )
            st.markdown("".join(blocks), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.button("← Back", on_click=prev_step, width="stretch")
        with c2:
            if st.button("Classify replies →", type="primary", width="stretch"):
                st.session_state.replies_built = False
                st.session_state.step = 4
                st.rerun()

# --- STEP 4: REPLIES ---
elif st.session_state.step == 4:
    st.markdown(
        section_header(
            "Reply intelligence",
            "Paste sample replies for each lead email (in-house). Claude / OpenAI classifies. "
            "Positive replies release the outreach lock for SDR follow-up; exhaustion after max touches recommends a call task.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    if le is None or le.empty:
        st.warning("No enriched leads to attach replies to.")
    else:
        st.text_area(
            "Paste replies as JSON list: [{\"email\":\"...\",\"text\":\"...\"}, ...]",
            height=160,
            key="replies_json_in",
        )
        if st.button("Parse + classify replies", width="stretch"):
            st.session_state.replies = []
            raw = (st.session_state.get("replies_json_in") or "").strip()
            try:
                items = json.loads(raw) if raw else []
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON: {exc}")
                items = []
            if not isinstance(items, list):
                st.error("Replies JSON must be a list.")
            else:
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    em = str(it.get("email") or "").strip()
                    txt = str(it.get("text") or "").strip()
                    if not em or not txt:
                        continue
                    lab = classify_reply_text(txt)
                    st.session_state.replies.append(
                        {
                            "name": em,
                            "text": txt,
                            "label": lab,
                            "email": em,
                            "crm": crm_eligible(lab),
                        }
                    )
                    if lab in (REPLY_NOT_INTERESTED, REPLY_UNSUBSCRIBE):
                        st.session_state.blacklist.add(em)
                st.session_state.replies_built = True
                st.rerun()

    if st.session_state.replies:
        st.markdown("**Inbox (structured)**", unsafe_allow_html=True)
        rdf = pd.DataFrame(st.session_state.replies)
        cols = [c for c in ("name", "text", "label", "email") if c in rdf.columns]
        st.dataframe(rdf[cols], width="stretch", hide_index=True)
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, width="stretch")
    with c2:
        if st.button("Sync CRM state →", type="primary", width="stretch"):
            st.session_state.step = 5
            st.rerun()

# --- STEP 5: CRM ---
elif st.session_state.step == 5:
    st.markdown(
        section_header(
            "CRM (in-house + HubSpot)",
            "Leads enter after enrich as queued for outreach with an active outreach lock. "
            "SDRs see assignment and state, but the system coordinates touches until release rules apply. "
            "Use **Send to HubSpot** to create or update HubSpot contacts (by email) and attach a timeline note "
            "with job links, intent score, and posting context.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    assigned = str(st.session_state.get("assigned_sdr_label") or "SDR Team").strip() or "SDR Team"
    if le is not None and not le.empty and not st.session_state.crm_records:
        st.session_state.crm_records = seed_crm_from_enriched(le, assigned, st.session_state.blacklist)
    recs = apply_blacklist_to_records(list(st.session_state.crm_records or []), st.session_state.blacklist)
    recs = refresh_crm_after_replies(recs, st.session_state.replies)
    st.session_state.crm_records = recs
    if recs:
        try:
            append_event("crm_records", {"records": recs})
        except NocoDBError as exc:
            st.warning(f"Could not log CRM batch to NocoDB events table: {exc}")
    st.dataframe(to_crm_dataframe(recs), width="stretch", hide_index=True)
    if hubspot_configured():
        st.caption(
            "HubSpot: token is set. Sync upserts by **email** (existing contacts get an updated profile "
            "where fields are present and a **new note** on the record). "
            "Sequences and one-to-one email from HubSpot use your connected inbox in HubSpot settings."
        )
    else:
        st.caption(
            "HubSpot: add **HUBSPOT_ACCESS_TOKEN** (private app token with `crm.objects.contacts` read/write "
            "and `crm.objects.notes` write) to `.env` or Streamlit secrets to enable **Send to HubSpot**."
        )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.button("← Back", on_click=prev_step, width="stretch")
    with c2:
        hs_token = hubspot_access_token()
        hs_disabled = not hs_token or not recs
        if st.button(
            "Send to HubSpot",
            width="stretch",
            disabled=hs_disabled,
            help="Creates or updates HubSpot contacts from visible CRM rows (skips rows with no email and DNC).",
        ):
            email_to_lead = _email_to_enriched_lead(le)
            to_push = [
                r
                for r in recs
                if isinstance(r, dict)
                and str(r.get("lead_status") or "") != LEAD_STATUS_DNC
                and str(r.get("email") or "").strip()
            ]
            summary = push_crm_batch(hs_token, to_push, email_to_lead)
            for err in (summary.get("errors") or [])[:20]:
                st.warning(str(err))
            safe_toast(
                f"HubSpot: {summary.get('ok', 0)} synced · skipped (no email): {summary.get('skipped', 0)}",
                icon="✅",
            )
            try:
                append_event(
                    "hubspot_push",
                    {
                        "ok": summary.get("ok"),
                        "skipped": summary.get("skipped"),
                        "errors_n": len(summary.get("errors") or []),
                    },
                )
            except NocoDBError:
                pass
            st.rerun()
    with c3:
        if st.button("View dashboard →", type="primary", width="stretch"):
            st.session_state.step = 6
            st.rerun()

# --- STEP 6: DASHBOARD ---
else:
    st.markdown(
        section_header(
            "Live performance",
            "Operational view of the in-house pipeline (generation + logging).",
        ),
        unsafe_allow_html=True,
    )
    sc = st.session_state.company_scored
    n_leads = len(sc) if sc is not None and not sc.empty else 0
    replies = st.session_state.replies
    n_rep = len(replies)
    n_pos = sum(1 for r in replies if r.get("label") == REPLY_INTERESTED)
    n_unsub = sum(1 for r in replies if r.get("label") == REPLY_UNSUBSCRIBE)
    d = build_dashboard(
        n_leads_generated=n_leads,
        emails_sent=st.session_state.emails_sent_count,
        walego_actions=st.session_state.walego_actions,
        company_scored=sc,
        replies_total=n_rep,
        positive_replies=n_pos,
        unsubscribes=n_unsub,
        walego_accepted=st.session_state.walego_accepted,
        walego_requests=max(st.session_state.walego_requests, 1),
        interested_in_crm=sum(
            1
            for r in (st.session_state.crm_records or [])
            if str(r.get("deal_status") or r.get("status") or "") == "Interested"
        ),
        booked_calls=0,
        active_conversations=max(0, n_pos - 0),
        stalled_leads=max(0, n_rep - n_pos - n_unsub),
    )
    t = d["top"]
    i = d["intent"]
    e = d["engagement"]
    c = d["conversions"]
    h = d["health"]
    st.markdown(
        render_stat_grid(
            [
                (
                    "Top of funnel",
                    [
                        (str(t["leads_generated"]), "Leads generated"),
                        (str(t["emails_sent"]), "Dispatch logs"),
                        (str(t["linkedin_actions"]), "Walego handoffs"),
                    ],
                ),
                (
                    "Intent quality",
                    [
                        (str(i["high"]), "High intent"),
                        (str(i["medium"]), "Medium"),
                        (str(i["low"]), "Low"),
                        (str(i["avg_intent_score"]), "Avg score"),
                    ],
                ),
                (
                    "Engagement",
                    [
                        (str(e["replies"]), "Replies"),
                        (str(e["reply_rate_pct"]), "Reply rate %"),
                        (str(e["positive_reply_rate_pct"]), "Positive %"),
                        (str(e["unsubscribes"]), "Unsubscribes"),
                        (str(e["linkedin_acceptance_rate_pct"]), "LI accept %"),
                    ],
                ),
                (
                    "Conversions",
                    [
                        (str(c["interested_in_crm"]), "Interested in CRM"),
                        (str(c["booked_calls"]), "Booked calls"),
                        (str(c["lead_to_call_rate_pct"]), "Lead → call %"),
                    ],
                ),
                (
                    "Pipeline health",
                    [
                        (str(h["active_conversations"]), "Active conv."),
                        (str(h["stalled_leads"]), "Stalled (est.)"),
                    ],
                ),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.button("← Back to CRM", on_click=prev_step, width="stretch")
