import streamlit as st
import pandas as pd
import time
from html import escape
from leads import get_mock_leads, filter_high_intent
from enrichment import waterfall_enrichment
from outreach import personalize_template

# --- PAGE CONFIG ---
st.set_page_config(page_title="IntentFlow", page_icon="🚀", layout="wide")

# Initialize Step
if 'step' not in st.session_state:
    st.session_state.step = 0

def next_step(): st.session_state.step += 1
def prev_step(): st.session_state.step -= 1

# --- STREAMLINED BEIGE & WHITE CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap');
    
    /* Backgrounds */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], [data-testid="stHeader"] { 
        background-color: #fdfbf7 !important; 
    }
    
    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }
    
    /* Global Text */
    h1, h2, h3, h4, h5, h6, p, li, span, label, div { 
        color: #2d2d2d !important; 
    }
    
    /* Stepper Header */
    .step-item { 
        color: #b0a695 !important; 
        font-weight: 700; font-size: 0.7rem; 
        letter-spacing: 1.5px; text-align: center; 
        border-bottom: 2px solid #e8e4db; padding-bottom: 8px; 
    }
    .step-item.active { 
        color: #6366f1 !important; 
        border-bottom: 2px solid #6366f1 !important; 
    }
    
    /* Remove redundant st.container card styling */
    [data-testid="stVerticalBlock"] > div > div { 
        background: transparent !important; 
        border: none !important; 
        box-shadow: none !important; 
        padding: 0 !important;
        margin-bottom: 0 !important;
    }

    /* Primary Content Card */
    .content-card {
        background: #ffffff;
        padding: 25px;
        border-radius: 12px;
        border: 1px solid #e8e4db;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
        margin-bottom: 20px;
    }

    /* Email Draft Box */
    .email-draft-box { 
        background: #faf9f6 !important; 
        border: 1px solid #e8e4db !important; 
        border-radius: 8px; 
        padding: 12px; 
        font-size: 0.9rem !important; 
        color: #2d2d2d !important; 
        margin-bottom: 10px;
    }

    /* Professional Buttons */
    .stButton > button {
        border-radius: 8px !important;
        font-weight: 700 !important;
        background-color: #ffffff !important;
        color: #2d2d2d !important;
        border: 1px solid #e8e4db !important;
    }
    .stButton > button[kind="primary"] {
        background-color: #6366f1 !important;
        color: #ffffff !important;
        border: none !important;
    }
    
    /* Sidebar Cleanup */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        padding: 2rem 1.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("<h2 style='color:#6366f1; margin-top:0;'>IntentFlow</h2>", unsafe_allow_html=True)
    st.markdown("### Campaign Control")
    min_score = st.slider("Intent Threshold", 50, 100, 80)
    test_email = st.text_input("Destination Email", placeholder="you@example.com")
    st.write("<br>", unsafe_allow_html=True)
    if st.button("Reset Workflow", use_container_width=True):
        st.session_state.step = 0
        if 'enriched' in st.session_state: del st.session_state.enriched
        st.rerun()

# --- DATA ---
df = get_mock_leads()
filtered = filter_high_intent(df, min_score)

# --- LOGO & BRANDING ---
st.markdown("<div style='text-align: left; margin-top: -40px; margin-bottom: 0px;'><img src='https://cdn-icons-png.flaticon.com/512/115/115795.png' width='50'></div>", unsafe_allow_html=True)

# --- STEPPER ---
st.write("")
cols = st.columns(4)
steps = ["DISCOVERY", "ENRICHMENT", "OUTREACH", "CAMPAIGN"]
for i, s in enumerate(steps):
    active = "active" if st.session_state.step == i else ""
    cols[i].markdown(f"<div class='step-item {active}'>{s}</div>", unsafe_allow_html=True)
st.write("<br>", unsafe_allow_html=True)

# --- WINDOWS ---

# WINDOW 0: DISCOVERY
if st.session_state.step == 0:
    st.markdown("### 🔍 Lead Discovery")
    st.markdown("<div class='content-card'>", unsafe_allow_html=True)
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    if st.button("Proceed to Enrichment →", type="primary", use_container_width=True):
        next_step()
        st.rerun()

# WINDOW 1: ENRICHMENT
elif st.session_state.step == 1:
    st.markdown("### 🔄 Waterfall Enrichment")
    st.markdown("<div class='content-card'>", unsafe_allow_html=True)
    if 'enriched' not in st.session_state:
        st.info("System ready for verification sequence.")
        if st.button("🚀 Start Waterfall Sync", type="primary", use_container_width=True):
            bar = st.progress(0)
            for i in range(100):
                time.sleep(0.01)
                bar.progress(i + 1)
            st.session_state.enriched = waterfall_enrichment(filtered)
            st.rerun()
    else:
        st.success("✅ Enrichment Complete")
        st.dataframe(st.session_state.enriched, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    if 'enriched' in st.session_state:
        c_p, c_n = st.columns(2)
        with c_p: st.button("← Back to Discovery", on_click=prev_step, use_container_width=True)
        with c_n: st.button("Go to Outreach →", on_click=next_step, type="primary", use_container_width=True)

# WINDOW 2: OUTREACH
elif st.session_state.step == 2:
    st.markdown("### 📧 Precision Outreach")
    st.markdown("<div class='content-card'>", unsafe_allow_html=True)
    if not test_email:
        st.warning("⚠️ Action Required: Provide an email in the sidebar.")
        if st.button("← Back to Enrichment", on_click=prev_step): st.rerun()
    else:
        c1, c2 = st.columns([1, 1.5])
        with c1:
            template = st.text_area("Master Template", value="Hey {{Name}},\n\nSaw your post about {{Signal}} at {{Company}}.\n\nOpen to chat?", height=200)
            st.markdown(f"""<form action="https://formsubmit.co/{test_email}" method="POST" target="_blank"><button type="submit" style="background:#ffffff;color:#6366f1;border:1px solid #6366f1;padding:12px;border-radius:10px;width:100%;cursor:pointer;font-weight:700;">Activate Identity</button></form>""", unsafe_allow_html=True)
        with c2:
            st.write("Draft Verification Queue:")
            for idx, lead in st.session_state.enriched.iterrows():
                with st.expander(f"✉️ Draft for {lead['Name']}"):
                    body = personalize_template(template, lead)
                    st.markdown(f"<div class='email-draft-box'>{body}</div>", unsafe_allow_html=True)
                    safe_name = escape(str(lead["Name"]))
                    safe_email = escape(str(lead["Email"]))
                    safe_company = escape(str(lead["Company"]))
                    safe_body = escape(str(body))
                    safe_subject = escape(f"IntentFlow Outreach: {lead['Name']} ({lead['Company']})")
                    safe_target_email = escape(test_email)
                    st.markdown(
                        f"""
                        <form action="https://formsubmit.co/{safe_target_email}" method="POST" target="_blank">
                            <input type="hidden" name="name" value="{safe_name}">
                            <input type="hidden" name="email" value="{safe_email}">
                            <input type="hidden" name="company" value="{safe_company}">
                            <input type="hidden" name="message" value="{safe_body}">
                            <input type="hidden" name="_subject" value="{safe_subject}">
                            <input type="hidden" name="_captcha" value="false">
                            <button type="submit" style="background:#6366f1;color:#fff;border:none;padding:10px;border-radius:8px;width:100%;cursor:pointer;font-weight:700;">
                                Dispatch 🚀
                            </button>
                        </form>
                        """,
                        unsafe_allow_html=True
                    )
    st.markdown("</div>", unsafe_allow_html=True)
    
    c_p, c_n = st.columns(2)
    with c_p: st.button("← Back", on_click=prev_step, use_container_width=True)
    with c_n: st.button("Campaign Summary →", on_click=next_step, type="primary", use_container_width=True)

# WINDOW 3: CAMPAIGN
elif st.session_state.step == 3:
    st.markdown("### 📊 Campaign Summary")
    st.markdown("<div class='content-card'>", unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("Leads Dispatched", len(st.session_state.enriched))
    m2.metric("Reach Rate", "100%")
    m3.metric("Status", "Active")
    st.write("<br>", unsafe_allow_html=True)
    st.dataframe(st.session_state.enriched[['Name', 'Company', 'Email']], use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    sc1, sc2, sc3 = st.columns(3)
    with sc1: st.button("Sync Salesforce", use_container_width=True)
    with sc2: st.button("Sync HubSpot", use_container_width=True)
    with sc3: st.button("Sync Pipedrive", use_container_width=True)
    st.write("---")
    st.button("Start New Workflow 🔄", on_click=lambda: st.session_state.update({"step": 0}), use_container_width=True)
