import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from config import (
    BRAND,
    CORPUS_CA_JOB_SHARE,
    CORPUS_US_JOB_SHARE,
    HIGH_INTENT_MAX_AGE_DAYS,
    MEDIUM_INTENT_MAX_AGE_DAYS,
    MAX_EMAILS_PER_INBOX_PER_DAY,
    MAX_JOB_POSTING_AGE_DAYS,
    REPLY_INTERESTED,
    REPLY_NOT_INTERESTED,
    REPLY_UNSUBSCRIBE,
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
from enrichment import waterfall_enrichment
from internal_intent import invalidate_intent_corpus_cache
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

# --- PAGE CONFIG ---
st.set_page_config(page_title=f"{BRAND} – Command Center", page_icon="✦", layout="wide")

# Session defaults
if "session_id" not in st.session_state:
    st.session_state.session_id = "default"
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
    st.session_state.step = max(0, st.session_state.step - 1)


def _serialize_blacklist() -> list[str]:
    return sorted({str(x) for x in st.session_state.blacklist})


def _deserialize_blacklist(items: list[str]) -> None:
    st.session_state.blacklist = set(items or [])


def _payload_for_save() -> dict:
    return {
        "company_jobs": st.session_state.company_jobs.to_dict(orient="records")
        if isinstance(st.session_state.company_jobs, pd.DataFrame)
        else None,
        "company_scored": st.session_state.company_scored.to_dict(orient="records")
        if isinstance(st.session_state.company_scored, pd.DataFrame)
        else None,
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
    }


def _hydrate_from_payload(payload: dict) -> None:
    def _df(key: str) -> pd.DataFrame | None:
        raw = payload.get(key)
        if raw is None:
            return None
        return pd.DataFrame(raw)

    st.session_state.company_jobs = _df("company_jobs")
    st.session_state.company_scored = _df("company_scored")
    st.session_state.leads_enriched = _df("leads_enriched")
    st.session_state.emails_sent_count = int(payload.get("emails_sent_count") or 0)
    st.session_state.walego_actions = int(payload.get("walego_actions") or 0)
    st.session_state.walego_accepted = int(payload.get("walego_accepted") or 0)
    st.session_state.walego_requests = int(payload.get("walego_requests") or 0)
    st.session_state.replies = list(payload.get("replies") or [])
    _deserialize_blacklist(list(payload.get("blacklist") or []))
    st.session_state.crm_records = list(payload.get("crm_records") or [])
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


@st.fragment(run_every=timedelta(seconds=0.42))
def _client_welcome_background_fragment() -> None:
    """Polls prefetch completion and animates native progress while the welcome screen is visible."""
    if st.session_state.get("client_landing_dismissed"):
        return
    merged = _try_merge_prefetch_future()
    if merged and not st.session_state.get("_prefetch_ready_toast_shown"):
        st.toast("Intent snapshot is ready — enter the command center when you like.", icon="✨")
        st.session_state._prefetch_ready_toast_shown = True
    prog_slot = st.empty()
    fut = st.session_state.get("_intent_prefetch_future")
    if st.session_state.get("_intent_prefetch_ready"):
        prog_slot.progress(1.0, text="Intent snapshot ready")
    elif fut is not None and not fut.done():
        pulse = 0.18 + 0.72 * (0.5 + 0.5 * math.sin(time.monotonic() * 2.05))
        prog_slot.progress(min(0.94, pulse), text="Fetching listings & scores in the background…")
    elif st.session_state.get("_intent_prefetch_error"):
        prog_slot.warning("Background fetch reported an issue — we will retry after you enter.")
    elif st.session_state.get("_intent_prefetch_submitted"):
        prog_slot.progress(0.12, text="Starting background pull…")
    else:
        prog_slot.progress(0.05, text="Preparing background pull…")


def _save_to_nocodb() -> None:
    payload = _payload_for_save()
    upsert_snapshot(st.session_state.session_id, int(st.session_state.step), payload)
    append_event("pipeline_save", {"session_id": st.session_state.session_id, "step": st.session_state.step})


def _hydrate_from_nocodb() -> None:
    if st.session_state.nocodb_hydrated:
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
                pipe.update(
                    label=f"Done — {nj} job postings, {nc} companies scored.",
                    state="complete",
                )
        except Exception as exc:
            if pipe_ref is not None:
                pipe_ref.update(
                    label=f"Intent failed: {exc}",
                    state="error",
                )
            st.error(
                "Intent stage failed. Check LLM / OpenRouter API keys and `LLM_PROVIDER_ORDER` in `.env` or "
                "Streamlit secrets. For live Indeed/LinkedIn rows, install **`python-jobspy`** (not the PyPI "
                f"package named `jobspy`). Details: {exc}"
            )
            st.session_state.company_jobs = pd.DataFrame()
            st.session_state.company_scored = pd.DataFrame()
        finally:
            prog.empty()
            stream_info_slot.empty()
            stream_table_slot.empty()


st.markdown(get_global_css(), unsafe_allow_html=True)

# Native Streamlit boot: first paint only (avoids flashing on every rerun).
if not st.session_state._native_session_bootstrap_done:
    with st.status("Starting hirequity", expanded=False) as _boot:
        _boot.update(label="Loading saved pipeline from NocoDB…", state="running")
        _hydrate_from_nocodb()
        _boot.update(label="Resolving viewer region for job mix…", state="running")
        _viewer_geo_maybe_refresh()
        _boot.update(label="Workspace ready.", state="complete")
    st.session_state._native_session_bootstrap_done = True
else:
    _hydrate_from_nocodb()
    _viewer_geo_maybe_refresh()

# --- SIDEBAR ---
with st.sidebar:
    st.markdown(
        """
        <div style="padding:0.1rem 0 0.9rem;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:1rem;">
        <span style="font-size:0.62rem;letter-spacing:0.22em;text-transform:uppercase;color:#a78bfa;">Session</span><br/>
        <span style="font-size:1.15rem;font-weight:700;background:linear-gradient(90deg,#fff,#c4b5fd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">hirequity</span>
        <p style="margin:0.35rem 0 0;font-size:0.78rem;color:#71717a !important;">In-house · OpenRouter + NocoDB</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input("Session id", value=st.session_state.session_id, key="session_id_in")
    st.text_input(
        "Assigned SDR (CRM visibility)",
        key="assigned_sdr_label",
        help="Shown on every lead after enrich. Automation still holds the outreach lock until release rules fire.",
    )

    def _apply_session():
        st.session_state.session_id = (st.session_state.session_id_in or "default").strip()
        st.session_state.nocodb_hydrated = False
        st.session_state._native_session_bootstrap_done = False
        st.session_state.client_landing_dismissed = False
        st.session_state._intent_prefetch_submitted = False
        st.session_state.pop("_intent_prefetch_future", None)
        st.session_state.pop("_intent_prefetch_ready", None)
        st.session_state.pop("_prefetch_ready_toast_shown", None)
        st.session_state.pop("_intent_prefetch_error", None)
        st.session_state.pop("_intent_geo_key_applied", None)
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
    min_tier = st.multiselect("Outreach tiers", ["High", "Medium"], default=["High", "Medium"])
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

    if st.button("Save pipeline to NocoDB", width="stretch"):
        try:
            _save_to_nocodb()
            st.success("Saved snapshot to NocoDB.")
        except NocoDBError as exc:
            st.error(str(exc))

    if st.button("Reset pipeline", width="stretch"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.session_state.step = 0
        st.session_state.blacklist = set()
        st.session_state.outreach_simulated = False
        st.session_state.replies_built = False
        st.session_state.session_id = "default"
        st.session_state.session_id_in = "default"
        st.session_state.nocodb_hydrated = False
        st.session_state._native_session_bootstrap_done = False
        st.session_state.max_job_age_days = MAX_JOB_POSTING_AGE_DAYS
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
    _maybe_start_client_intent_prefetch()
    _client_welcome_background_fragment()
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
                "**(2)** Missing or invalid **LLM / OpenRouter** keys for the synthetic fallback. "
                "**(3)** Try **Regenerate intent corpus** after fixing env."
            )
    with d2:
        st.markdown(
            glass_card_start("Company intelligence")
            + "<p>Signals: role age, &gt;14d urgency, multi-role hiring, social mentions.</p>"
            + glass_card_end(),
            unsafe_allow_html=True,
        )
        st.dataframe(scored if scored is not None and not scored.empty else pd.DataFrame(), width="stretch", hide_index=True)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.button("Back", disabled=True, width="stretch")
    with c2:
        if st.button("Continue to scoring →", type="primary", width="stretch"):
            st.session_state.step = 1
            st.rerun()
    if st.button("Regenerate intent corpus (OpenRouter)", width="stretch"):
        invalidate_intent_corpus_cache()
        st.session_state.company_jobs = None
        st.session_state.company_scored = None
        st.toast("Refreshing intent — watch the status block above.", icon="🔄")
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
    ready = filter_outreach_ready(scored) if scored is not None and not scored.empty else pd.DataFrame()
    if (not min_tier) and ready is not None and not ready.empty:
        ready = pd.DataFrame()
    elif min_tier and ready is not None and not ready.empty:
        ready = ready[ready["Intent tier"].isin(min_tier)]
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
        if st.button("Run enrichment →", type="primary", width="stretch"):
            st.session_state.step = 2
            st.rerun()

# --- STEP 2: ENRICHMENT ---
elif st.session_state.step == 2:
    st.markdown(
        section_header(
            "Enrichment",
            "OpenRouter generates structured decision-maker profiles for drafting. Treat emails as fictional until you connect real verification. "
            "Next step pushes leads into CRM as queued for automation (not free-for-SDR manual work yet).",
        ),
        unsafe_allow_html=True,
    )
    ready = st.session_state.get("_ready_for_enrich", pd.DataFrame())
    st.markdown("<div class='hq-glass'>", unsafe_allow_html=True)
    if st.session_state.leads_enriched is None:
        if st.button("Execute enrichment", type="primary", width="stretch"):
            bar = st.progress(0)
            for i in range(100):
                time.sleep(0.006)
                bar.progress(i + 1)
            if ready is None or ready.empty:
                st.error("No qualified companies. Return to scoring.")
            else:
                try:
                    st.session_state.leads_enriched = waterfall_enrichment(ready)
                except Exception as exc:
                    st.error(f"Enrichment failed. Details: {exc}")
            st.rerun()
    else:
        st.success("Contacts generated — ready for sequence drafting.")
        st.dataframe(st.session_state.leads_enriched, width="stretch", hide_index=True)
        if st.button("Generate smart role-based email suggestions", width="stretch"):
            st.session_state.role_suggestions = role_based_suggestions(st.session_state.leads_enriched)
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
            "Sequences are generated with OpenRouter. Dispatch logs to NocoDB (no third-party email send in this build). "
            "CRM rows stay system-coordinated until replies or exhaustion release the outreach lock for SDR action.",
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
        if st.button("Log outreach dispatch to NocoDB", type="primary", width="stretch") or st.session_state.outreach_simulated:
            st.session_state.outreach_simulated = True
            if st.session_state.emails_sent_count == 0 and st.session_state.walego_actions == 0:
                if not st.session_state.crm_records:
                    assigned = str(st.session_state.get("assigned_sdr_label") or "SDR Team").strip() or "SDR Team"
                    st.session_state.crm_records = seed_crm_from_enriched(le, assigned, st.session_state.blacklist)
                sent_count = 0
                w_req = 0
                touches_by_email: dict[str, int] = {}
                skipped_high_intent: list[str] = []
                for _, lead in le.iterrows():
                    em_addr = str(lead.get("Email", ""))
                    if em_addr in st.session_state.blacklist:
                        continue
                    em_key = em_addr.strip().lower()
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
                        ok, msg = dispatch_email_internal(str(lead.get("Email", "")), em["subject"], em["body"])
                        if ok:
                            lead_sent += 1
                        else:
                            st.warning(f"Dispatch log failed for {lead.get('Email')}: {msg}")
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
                if skipped_high_intent:
                    st.info(
                        "High-intent hold: sequence paused until SDR review for: "
                        + ", ".join(skipped_high_intent[:12])
                        + ("…" if len(skipped_high_intent) > 12 else "")
                    )
        for _, lead in le.iterrows():
            if str(lead.get("Email", "")) in st.session_state.blacklist:
                continue
            n = escape(str(lead.get("Name", "")))
            c = escape(str(lead.get("Company", "")))
            seq = build_email_sequence(lead)
            blocks = [
                '<div class="hq-lead">',
                f"<h4>{n}</h4><div class=\"meta\">{c} · Email-first sequence (max 3) + Walego handoff</div>",
            ]
            for em in seq:
                blocks.append(
                    f'<div class="email-draft-box"><b>Touch {em["step"]}</b> · {escape(em["subject"])}<br><br>{escape(em["body"])}</div>'
                )
            blocks.append(
                f'<p class="meta">Walego JSON payload (execution layer)</p><pre style="font-size:0.75rem;opacity:0.9;">{escape(handoff_to_walego(lead))}</pre>'
            )
            blocks.append("<p class=\"meta\">Walego handoff generated (in-house payload).</p></div>")
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
            "Paste sample replies for each lead email (in-house). OpenRouter classifies. "
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
            "CRM (in-house)",
            "Leads enter after enrich as queued for outreach with an active outreach lock. "
            "SDRs see assignment and state, but the system coordinates touches until release rules apply.",
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
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, width="stretch")
    with c2:
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
