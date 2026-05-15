"""Env + Streamlit secrets lookup (no app config / dataclasses — safe during hot reload)."""
from __future__ import annotations

import os


def lookup_str(name: str, default: str | None = None) -> str | None:
    """Resolve a setting from process env, then Streamlit Cloud secrets."""
    raw = os.getenv(name)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip()
    try:
        import streamlit as st

        sec = getattr(st, "secrets", None)
        if sec is not None and name in sec:
            val = sec[name]
            if val is not None and str(val).strip() != "":
                return str(val).strip()
    except Exception:
        pass
    return default


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")
