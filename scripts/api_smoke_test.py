#!/usr/bin/env python3
"""
Smoke-test external HTTP APIs used by IntentEngine before client handoff.

Run from repo root (use Python 3.10+ venv):
  .venv/bin/python scripts/api_smoke_test.py

Checks: compileall, imports, ip-api, LLM (Anthropic + OpenAI), NocoDB, Apollo,
HubSpot, MailerSend, python-jobspy (Indeed sample). Loads `.env` via config on import.
Exit 0 if no hard failures (optional credentials missing → SKIP, not fail).
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

# Repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT: list[tuple[str, str, str]] = []  # (step, status, detail)


def step_compileall() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(ROOT)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        log("compileall", "FAIL", (exc.stderr or exc.stdout or str(exc))[:500])
        return False
    log("compileall", "PASS", "all .py under repo")
    return True


def log(step: str, status: str, detail: str = "") -> None:
    REPORT.append((step, status, detail))
    line = f"[{status:6}] {step}"
    if detail:
        line += f" — {detail}"
    print(line)


def step_imports() -> bool:
    """Import application modules (not ``main`` — Streamlit expects ``streamlit run``)."""
    try:
        import config  # noqa: F401

        for name in (
            "nocodb_rest",
            "llm_client",
            "user_geo",
            "pipeline",
            "enrichment",
        ):
            __import__(name)
    except Exception as exc:
        log("Imports", "FAIL", f"{exc!r}")
        traceback.print_exc()
        return False
    log("Imports", "PASS", "config, nocodb_rest, llm_client, user_geo, pipeline, enrichment")
    return True


def step_ip_api() -> bool:
    from user_geo import lookup_ip_geo

    g = lookup_ip_geo("8.8.8.8", timeout_seconds=8.0)
    if g.get("ok") and g.get("countryCode"):
        log("ip-api.com (Google DNS IP)", "PASS", f"{g.get('countryCode')} / {g.get('city') or g.get('regionName')}")
        return True
    log("ip-api.com (Google DNS IP)", "FAIL", g.get("message") or str(g))
    return False


def step_llm() -> bool:
    try:
        from llm_client import LLMError, chat_completion
    except Exception as exc:
        log("LLM client import", "FAIL", str(exc))
        return False

    try:
        out = chat_completion(
            [{"role": "user", "content": 'Reply with exactly the word: pong'}],
            0.0,
            task="default",
        ).strip()
    except LLMError as exc:
        log("LLM chat completion (Claude / OpenAI)", "SKIP", str(exc))
        return True
    except Exception as exc:
        log("LLM chat completion (Claude / OpenAI)", "FAIL", str(exc))
        traceback.print_exc()
        return False

    if "pong" in out.lower():
        log("LLM chat completion (Claude / OpenAI)", "PASS", out[:120])
        return True
    log("LLM chat completion (Claude / OpenAI)", "FAIL", f"unexpected reply: {out[:200]!r}")
    return False


def _nocodb_table_id_placeholder(table_id: str) -> bool:
    t = (table_id or "").strip().lower()
    return not t or "replace" in t or t.endswith("_table_id") or t == "tbl"


def step_apollo() -> bool:
    from apollo_enrichment import apollo_contact_enrichment_available, apollo_quick_probe

    if not apollo_contact_enrichment_available():
        log("Apollo.io (people search)", "SKIP", "APOLLO_API_KEY not set")
        return True
    ok, msg = apollo_quick_probe()
    log("Apollo.io (people search)", "PASS" if ok else "FAIL", msg)
    return ok


def step_hubspot() -> bool:
    import requests

    from config import hubspot_access_token, hubspot_configured

    if not hubspot_configured():
        log("HubSpot CRM API", "SKIP", "HUBSPOT_ACCESS_TOKEN / HUBSPOT_PRIVATE_APP_TOKEN not set")
        return True
    token = hubspot_access_token()
    try:
        r = requests.get(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 1},
            timeout=30,
        )
    except requests.RequestException as exc:
        log("HubSpot CRM API", "FAIL", f"network: {exc}")
        return False
    if r.status_code in (401, 403):
        log("HubSpot CRM API", "FAIL", f"HTTP {r.status_code}: token rejected")
        return False
    if r.status_code >= 400:
        log("HubSpot CRM API", "FAIL", f"HTTP {r.status_code}: {r.text[:240]}")
        return False
    log("HubSpot CRM API", "PASS", f"HTTP {r.status_code} — contacts endpoint reachable")
    return True


def step_mailersend() -> bool:
    from config import mailersend_configured
    from mailersend_client import mailersend_quick_probe

    if not mailersend_configured():
        log("MailerSend API", "SKIP", "MAILERSEND_API_TOKEN / MAILERSEND_FROM_EMAIL not set")
        return True
    ok, msg = mailersend_quick_probe()
    log("MailerSend API", "PASS" if ok else "FAIL", msg)
    return ok


def step_jobspy() -> bool:
    from internal_intent import jobspy_runtime_status

    js = jobspy_runtime_status()
    if not js.get("python_ok"):
        log("python-jobspy (Indeed/LinkedIn)", "FAIL", js.get("hint") or js.get("error"))
        return False
    if not js.get("jobspy_ok"):
        log("python-jobspy (Indeed/LinkedIn)", "FAIL", js.get("error") or "import failed")
        return False

    try:
        from jobspy import scrape_jobs
    except Exception as exc:
        log("python-jobspy (Indeed/LinkedIn)", "FAIL", str(exc))
        return False

    try:
        df = scrape_jobs(
            site_name=["indeed"],
            search_term="account executive",
            location="United States",
            results_wanted=5,
            hours_old=24 * 14,
            country_indeed="usa",
        )
    except Exception as exc:
        log("Indeed live scrape (jobspy)", "FAIL", str(exc)[:240])
        return False
    n = 0 if df is None else len(df)
    if n == 0:
        log("Indeed live scrape (jobspy)", "WARN", "0 rows — board may be throttling; runtime import OK")
        return True
    log("Indeed live scrape (jobspy)", "PASS", f"{n} listing(s) returned")
    return True


def step_nocodb() -> bool:
    try:
        from config import get_nocodb_settings
        from nocodb_rest import NocoDBError, list_records

        s = get_nocodb_settings()
    except RuntimeError as exc:
        log("NocoDB list_records", "SKIP", str(exc))
        return True

    if _nocodb_table_id_placeholder(s.table_id):
        log("NocoDB list_records", "SKIP", "NOCODB_PIPELINE_TABLE_ID still looks like a template; set a real table id.")
        return True

    try:
        rows = list_records(s.table_id, limit=3)
        log("NocoDB list_records", "PASS", f"{len(rows)} row(s) sample from pipeline table")
        return True
    except NocoDBError as exc:
        log("NocoDB list_records", "FAIL", str(exc))
        return False


def main() -> int:
    os.chdir(ROOT)
    print("IntentEngine API smoke test")
    print(f"cwd={ROOT}")
    print("---")
    ok = True
    ok = step_compileall() and ok
    ok = step_imports() and ok
    ok = step_ip_api() and ok
    ok = step_llm() and ok
    ok = step_nocodb() and ok
    ok = step_apollo() and ok
    ok = step_hubspot() and ok
    ok = step_mailersend() and ok
    ok = step_jobspy() and ok
    print("---")
    print("Summary")
    for step, status, detail in REPORT:
        print(f"  {status:6}  {step}" + (f"  |  {detail}" if detail else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
