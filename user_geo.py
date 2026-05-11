"""
Approximate viewer location from connection IP (for regional job corpus bias).
Uses ip-api.com free tier (no API key; do not call excessively).
"""
from __future__ import annotations

import ipaddress
from typing import Any, Optional

import requests

# ~95% US+Canada in corpus; remainder international (aligned with product ask)
NA_COUNTRY_CODES = frozenset({"US", "CA"})


def corpus_geo_cache_key(geo_hint: Optional[dict[str, Any]]) -> str:
    """Stable key for corpus cache + session intent invalidation."""
    if not geo_hint:
        return "default"
    return f"{str(geo_hint.get('countryCode') or '')}|{str(geo_hint.get('city') or '')}"


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved)


def resolve_client_ip() -> str | None:
    """Best-effort client IP from Streamlit (local dev often returns None)."""
    try:
        import streamlit as st

        ctx = getattr(st, "context", None)
        if ctx is None:
            return None
        ip = getattr(ctx, "ip_address", None)
        if ip:
            s = str(ip).strip()
            if s and s.lower() not in ("none", "127.0.0.1", "::1"):
                return s
        headers = getattr(ctx, "headers", None) or {}
        if hasattr(headers, "get"):
            xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
            if xff:
                return str(xff).split(",")[0].strip() or None
            xri = headers.get("X-Real-Ip") or headers.get("x-real-ip")
            if xri:
                return str(xri).strip() or None
    except Exception:
        pass
    return None


def lookup_ip_geo(ip: str, timeout_seconds: float = 4.0) -> dict[str, Any]:
    """
    Returns keys: ok, country, countryCode, regionName, city, message.
    """
    out: dict[str, Any] = {
        "ok": False,
        "country": "",
        "countryCode": "",
        "regionName": "",
        "city": "",
        "message": "",
    }
    if not ip or not _is_public_ip(ip):
        out["message"] = "private_or_invalid_ip"
        return out
    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,message,country,countryCode,regionName,city"},
            timeout=timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        out["message"] = str(exc)
        return out
    if not isinstance(data, dict) or data.get("status") != "success":
        out["message"] = str(data.get("message") or "lookup_failed")
        return out
    out["ok"] = True
    out["country"] = str(data.get("country") or "")
    out["countryCode"] = str(data.get("countryCode") or "").upper()
    out["regionName"] = str(data.get("regionName") or "")
    out["city"] = str(data.get("city") or "")
    return out


def build_geo_hint_for_corpus() -> dict[str, Any]:
    """
    Structured hint for LLM prompts + corpus cache key.
    Safe to call from Streamlit each rerun (caller should throttle lookups).
    """
    ip = resolve_client_ip()
    hint: dict[str, Any] = {
        "ip": ip,
        "country": "",
        "countryCode": "",
        "region": "",
        "city": "",
        "lookup_ok": False,
        "in_na": False,
    }
    if not ip:
        hint["summary"] = "Viewer IP unknown (e.g. local dev); default to major US and Canadian metros."
        return hint
    geo = lookup_ip_geo(ip)
    if not geo.get("ok"):
        hint["summary"] = (
            f"Viewer IP {ip} could not be resolved ({geo.get('message')}); "
            "default to major US and Canadian metros."
        )
        return hint
    hint["lookup_ok"] = True
    hint["country"] = geo.get("country") or ""
    hint["countryCode"] = geo.get("countryCode") or ""
    hint["region"] = geo.get("regionName") or ""
    hint["city"] = geo.get("city") or ""
    hint["in_na"] = hint["countryCode"] in NA_COUNTRY_CODES
    parts = [hint["city"], hint["region"], hint["country"]]
    loc = ", ".join(p for p in parts if p)
    hint["summary"] = f"Viewer approximates to {loc} (IP-derived)." if loc else "Viewer location resolved."
    return hint
