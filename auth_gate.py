"""Mandatory client login gate for hirequity (Streamlit session)."""
from __future__ import annotations

import streamlit as st

from ui_theme import get_login_css, render_login_headline, render_login_mesh_component

# Set on successful login; main.py applies before NocoDB hydrate / welcome prefetch.
HQ_NEEDS_LIVE_INTENT_KEY = "_hq_needs_live_intent"

VALID_CLIENT_ID = "SLE.HIREQUITY.V1"
VALID_PASSWORD = "lsof-ti"


def is_authenticated() -> bool:
    return bool(st.session_state.get("hq_authenticated"))


def verify_credentials(client_id: str, password: str) -> bool:
    cid = (client_id or "").strip()
    pwd = password or ""
    return cid == VALID_CLIENT_ID and pwd == VALID_PASSWORD


def ensure_auth_session_keys() -> None:
    if "hq_authenticated" not in st.session_state:
        st.session_state.hq_authenticated = False
    if "hq_login_error" not in st.session_state:
        st.session_state.hq_login_error = ""


def render_login_gate() -> None:
    """Full-screen login; call once per rerun and ``st.stop()`` after if still locked."""
    ensure_auth_session_keys()
    st.markdown(get_login_css(), unsafe_allow_html=True)
    st.markdown('<div class="hq-login-marker" aria-hidden="true"></div>', unsafe_allow_html=True)
    st.markdown('<div class="hq-login-card-wrap">', unsafe_allow_html=True)

    art_col, form_col = st.columns(2, gap="medium")
    with art_col:
        render_login_mesh_component()
    with form_col:
        st.markdown(render_login_headline(), unsafe_allow_html=True)
        st.markdown('<p class="hq-login-field-label">Client ID</p>', unsafe_allow_html=True)
        st.text_input(
            "Client ID",
            key="hq_login_client_id",
            placeholder="SLE.HIREQUITY.V1",
            label_visibility="collapsed",
        )
        st.markdown('<p class="hq-login-field-label">Password</p>', unsafe_allow_html=True)
        st.text_input(
            "Password",
            key="hq_login_password",
            type="password",
            placeholder="••••••••",
            label_visibility="collapsed",
        )
        err = st.session_state.get("hq_login_error") or ""
        if err:
            st.markdown(
                f'<p class="hq-login-status hq-login-status--err">{err}</p>',
                unsafe_allow_html=True,
            )
        login_col, _ = st.columns([1, 1.4])
        with login_col:
            if st.button("Login", type="primary", width="stretch", key="hq_login_submit"):
                if verify_credentials(
                    st.session_state.get("hq_login_client_id", ""),
                    st.session_state.get("hq_login_password", ""),
                ):
                    st.session_state.hq_authenticated = True
                    st.session_state.hq_login_error = ""
                    st.session_state[HQ_NEEDS_LIVE_INTENT_KEY] = True
                    st.rerun()
                st.session_state.hq_login_error = (
                    "Invalid Client ID or password. Contact Sledopyt AI for access."
                )
                st.rerun()
        st.markdown(
            '<p class="hq-login-foot">'
            "Session verification is required before workspace data loads. "
            "Credentials are issued per client deployment."
            "</p>",
            unsafe_allow_html=True,
        )
