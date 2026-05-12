#!/usr/bin/env python3
"""
Smoke-test external HTTP APIs used by IntentEngine (ip-api, LLM stack, NocoDB).

Run from repo root:
  python3 scripts/api_smoke_test.py

Loads `.env` via config when importing project modules. Exit 0 if no hard failures
(optional credentials missing → SKIP, not fail).
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
            "nocodb_client",
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
    log("Imports", "PASS", "config, nocodb_client, llm_client, user_geo, pipeline, enrichment")
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


def step_nocodb() -> bool:
    try:
        from config import get_nocodb_settings
        from nocodb_client import NocoDBError, list_records

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
    print("---")
    print("Summary")
    for step, status, detail in REPORT:
        print(f"  {status:6}  {step}" + (f"  |  {detail}" if detail else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
