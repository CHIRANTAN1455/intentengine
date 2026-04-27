import streamlit as st
import pandas as pd
import time
import hashlib
from html import escape

from config import BRAND, REPLY_UNSUBSCRIBE, REPLY_NOT_INTERESTED, REPLY_INTERESTED, MAX_EMAILS_PER_INBOX_PER_DAY
from pipeline import run_intent_stage, filter_outreach_ready
from enrichment import waterfall_enrichment
from email_engine import build_email_sequence
from deliverability import InboxStatus, plan_capacity
from walego import handoff_to_walego, mock_walego_engagement
from reply_classification import classify_reply_text, crm_eligible
from crm import build_crm_record, to_crm_dataframe
from dashboard_metrics import build_dashboard
from ui_theme import (
    get_global_css,
    render_hero,
    render_stepper,
    section_header,
    glass_card_start,
    glass_card_end,
    render_stat_grid,
    pill_for_reply,
)

# --- PAGE CONFIG ---
st.set_page_config(page_title=f"{BRAND} – Command Center", page_icon="✦", layout="wide")

# Session defaults
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


def prev_step():
    st.session_state.step = max(0, st.session_state.step - 1)


def _ensure_intent():
    if st.session_state.company_scored is None:
        jobs, scored = run_intent_stage()
        st.session_state.company_jobs = jobs
        st.session_state.company_scored = scored


st.markdown(get_global_css(), unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.markdown(
        """
        <div style="padding:0.1rem 0 0.9rem;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:1rem;">
        <span style="font-size:0.62rem;letter-spacing:0.22em;text-transform:uppercase;color:#a78bfa;">Session</span><br/>
        <span style="font-size:1.15rem;font-weight:700;background:linear-gradient(90deg,#fff,#c4b5fd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">HireQuity</span>
        <p style="margin:0.35rem 0 0;font-size:0.78rem;color:#71717a !important;">Intent Outbound · V1</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input("Destination email (optional)", placeholder="you@company.com", key="test_email_in")
    min_tier = st.multiselect("Outreach tiers", ["High", "Medium"], default=["High", "Medium"])
    if st.button("Reset pipeline", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.session_state.step = 0
        st.session_state.blacklist = set()
        st.session_state.outreach_simulated = False
        st.session_state.replies_built = False
        st.rerun()

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
            "Aggregate LinkedIn Jobs, Indeed, and Glassdoor with a sales-role lens, then layer social signals — volume is secondary to signal quality.",
        ),
        unsafe_allow_html=True,
    )
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(glass_card_start("Job postings") + "<p>Filtered: Sales Rep, AE, SDR, BDR, and related GTM roles.</p>" + glass_card_end(), unsafe_allow_html=True)
        st.dataframe(jobs if jobs is not None and not jobs.empty else pd.DataFrame(), use_container_width=True, hide_index=True)
    with d2:
        st.markdown(
            glass_card_start("Company intelligence")
            + "<p>Signals: role age, &gt;14d urgency, multi-role hiring, social mentions.</p>"
            + glass_card_end(),
            unsafe_allow_html=True,
        )
        st.dataframe(scored if scored is not None and not scored.empty else pd.DataFrame(), use_container_width=True, hide_index=True)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.button("Back", disabled=True, use_container_width=True)
    with c2:
        if st.button("Continue to scoring →", type="primary", use_container_width=True):
            st.session_state.step = 1
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
        st.dataframe(scored, use_container_width=True, hide_index=True)
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
        st.button("← Back", on_click=prev_step, use_container_width=True)
    with c2:
        if st.button("Run enrichment →", type="primary", use_container_width=True):
            st.session_state.step = 2
            st.rerun()

# --- STEP 2: ENRICHMENT ---
elif st.session_state.step == 2:
    st.markdown(
        section_header(
            "Waterfall enrichment",
            "Decision-makers (VP Sales, Head of Sales, Founder, People) — verified contact before a single send.",
        ),
        unsafe_allow_html=True,
    )
    ready = st.session_state.get("_ready_for_enrich", pd.DataFrame())
    st.markdown("<div class='hq-glass'>", unsafe_allow_html=True)
    if st.session_state.leads_enriched is None:
        st.info("Waterfall resolves name, title, email, phone, and LinkedIn — simulated in this build.")
        if st.button("Execute waterfall", type="primary", use_container_width=True):
            bar = st.progress(0)
            for i in range(100):
                time.sleep(0.006)
                bar.progress(i + 1)
            if ready is None or ready.empty:
                st.error("No qualified companies. Return to scoring.")
            else:
                st.session_state.leads_enriched = waterfall_enrichment(ready)
            st.rerun()
    else:
        st.success("Verification complete — contacts are ready for dual-channel outreach.")
        st.dataframe(st.session_state.leads_enriched, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, use_container_width=True)
    with c2:
        if st.session_state.leads_enriched is not None and st.button("Outreach sequence →", type="primary", use_container_width=True):
            st.session_state.step = 3
            st.rerun()

# --- STEP 3: OUTREACH ---
elif st.session_state.step == 3:
    st.markdown(
        section_header(
            "Dual-channel outreach",
            "Email is primary. Walego executes LinkedIn — we never duplicate messaging in-app.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    if le is None or le.empty:
        st.warning("Complete enrichment first.")
        st.button("← Back", on_click=prev_step, use_container_width=True)
    else:
        ib = InboxStatus(inbox_id="inbox-1", sent_today=st.session_state.emails_sent_count)
        st.markdown(
            f"<div class='hq-fade' style='margin-bottom:0.75rem;'>Deliverability: {escape(plan_capacity(ib.sent_today))} · cap {MAX_EMAILS_PER_INBOX_PER_DAY}/inbox/day · SPF / DKIM / warm-up required in production.</div>",
            unsafe_allow_html=True,
        )
        if st.button("Simulate email + Walego send", type="primary", use_container_width=True) or st.session_state.outreach_simulated:
            st.session_state.outreach_simulated = True
            if st.session_state.emails_sent_count == 0 and st.session_state.walego_actions == 0:
                w_act = 0
                w_req = 0
                w_acc = 0
                for _, lead in le.iterrows():
                    if str(lead.get("Email", "")) in st.session_state.blacklist:
                        continue
                    eng = mock_walego_engagement(lead)
                    w_req += 1
                    w_act += 1 + eng["messages_in_sequence"]
                    if eng["accepted"]:
                        w_acc += 1
                st.session_state.walego_actions = w_act
                st.session_state.walego_requests = w_req
                st.session_state.walego_accepted = w_acc
                st.session_state.emails_sent_count = len(le) * 3
        for _, lead in le.iterrows():
            if str(lead.get("Email", "")) in st.session_state.blacklist:
                continue
            n = escape(str(lead.get("Name", "")))
            c = escape(str(lead.get("Company", "")))
            seq = build_email_sequence(lead)
            blocks = [
                f'<div class="hq-lead">',
                f'<h4>{n}</h4><div class="meta">{c} · Email-first sequence (max 3) + Walego handoff</div>',
            ]
            for em in seq:
                blocks.append(
                    f'<div class="email-draft-box"><b>Touch {em["step"]}</b> · {escape(em["subject"])}<br><br>{escape(em["body"])}</div>'
                )
            blocks.append(f'<p class="meta">Walego JSON payload (execution layer)</p><pre style="font-size:0.75rem;opacity:0.9;">{escape(handoff_to_walego(lead))}</pre>')
            eng = mock_walego_engagement(lead)
            blocks.append(
                f'<p class="meta">Walego: connection sent · accepted={eng["accepted"]} · sequence depth={eng["messages_in_sequence"]}</p></div>'
            )
            st.markdown("".join(blocks), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.button("← Back", on_click=prev_step, use_container_width=True)
        with c2:
            if st.button("Classify replies →", type="primary", use_container_width=True):
                st.session_state.replies_built = False
                st.session_state.step = 4
                st.rerun()

# --- STEP 4: REPLIES ---
elif st.session_state.step == 4:
    st.markdown(
        section_header(
            "Reply intelligence",
            "Interested, not interested, or unsubscribe — only Interested flows to your CRM; others stop and blacklist where appropriate.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    if not st.session_state.replies_built:
        st.session_state.replies = []

        def _h(s: str) -> int:
            return int(hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)

        sample = [
            "Yes, let's do Tuesday at 2pm for a quick call.",
            "Not a fit for us right now, thanks.",
            "Please remove me from your list.",
        ]
        for i, s in enumerate(sample):
            label = classify_reply_text(s)
            st.session_state.replies.append(
                {"name": f"Sample {i+1}", "text": s, "label": label, "crm": crm_eligible(label)}
            )
        st.markdown("**Exemplar classifications**", unsafe_allow_html=True)
        for i, s in enumerate(sample):
            label = classify_reply_text(s)
            st.markdown(
                f'<div class="hq-glass" style="margin:0.35rem 0;">{pill_for_reply(label)} <span class="hq-fade" style="margin-left:0.3rem;">{escape(s[:120])}…</span></div>',
                unsafe_allow_html=True,
            )
        if le is not None and not le.empty:
            for _, lead in le.iterrows():
                em = str(lead.get("Email") or "")
                t = (
                    f"Interested in learning more at {lead.get('Company')}"
                    if (_h(em) % 2) == 0
                    else "No thanks, not the right time."
                )
                lab = classify_reply_text(t)
                st.session_state.replies.append(
                    {
                        "name": lead.get("Name"),
                        "text": t,
                        "label": lab,
                        "email": em,
                        "crm": crm_eligible(lab),
                    }
                )
                if lab in (REPLY_NOT_INTERESTED, REPLY_UNSUBSCRIBE) and em:
                    st.session_state.blacklist.add(em)
        st.session_state.replies_built = True
    if st.session_state.replies:
        st.markdown("**Inbox (structured)**", unsafe_allow_html=True)
        rdf = pd.DataFrame(st.session_state.replies)
        cols = [c for c in ("name", "text", "label", "email") if c in rdf.columns]
        st.dataframe(rdf[cols], use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, use_container_width=True)
    with c2:
        if st.button("Sync CRM (qualified) →", type="primary", use_container_width=True):
            st.session_state.step = 5
            st.rerun()

# --- STEP 5: CRM ---
elif st.session_state.step == 5:
    st.markdown(
        section_header(
            "CRM (downstream)",
            "Qualified only — with intent reason, full contact graph, and interaction history so a rep can act with zero cleanup.",
        ),
        unsafe_allow_html=True,
    )
    le = st.session_state.leads_enriched
    recs = []
    by_email = {}
    for r in st.session_state.replies or []:
        e = r.get("email")
        if e:
            by_email[str(e)] = r
    if le is not None and not le.empty:
        for _, lead in le.iterrows():
            hist = "Email: 1–3 touches · Walego: connection + sequence (mock engagement feed)."
            em = str(lead.get("Email") or "")
            rpl = by_email.get(em) if em else None
            lab = rpl.get("label") if rpl else REPLY_NOT_INTERESTED
            if crm_eligible(lab):
                recs.append(build_crm_record(lead, interaction_log=hist, status="Interested"))
    st.session_state.crm_records = recs
    st.dataframe(to_crm_dataframe(recs), use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    with c1:
        st.button("← Back", on_click=prev_step, use_container_width=True)
    with c2:
        if st.button("View dashboard →", type="primary", use_container_width=True):
            st.session_state.step = 6
            st.rerun()

# --- STEP 6: DASHBOARD ---
else:
    st.markdown(
        section_header(
            "Live performance",
            "What your client sees: funnel lift, quality split, channel engagement, conversion, and pipeline health.",
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
        interested_in_crm=len(st.session_state.crm_records or []),
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
                        (str(t["emails_sent"]), "Emails sent (sim)"),
                        (str(t["linkedin_actions"]), "LinkedIn actions"),
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
    st.button("← Back to CRM", on_click=prev_step, use_container_width=True)
