#!/usr/bin/env python3
"""Full smoke test for IntentEngine after the OpenRouter removal.

Runs in 5 stages and prints a compact report at the end:
  1. compileall            — every .py compiles
  2. imports               — every project module imports
  3. provider order        — default LLM order is anthropic,openai (no openrouter)
  4. policy gates          — enrichment is verified-only, dispatch is gated, etc.
  5. live listings         — python-jobspy pull from Indeed (real rows)
  6. LLM smoke (optional)  — Anthropic + OpenAI ping (SKIP if no key)

The script is read-only: it never writes to NocoDB or sends email.
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Make sure config-time required envs are present so importing config.py doesn't blow up.
os.environ.setdefault("NOCODB_API_TOKEN", "smoke_test_placeholder")
os.environ.setdefault("NOCODB_PIPELINE_TABLE_ID", "smoke_test_placeholder")

REPORT: list[tuple[str, str, str]] = []


def log(step: str, status: str, detail: str = "") -> None:
    REPORT.append((step, status, detail))
    line = f"  [{status:4}]  {step}"
    if detail:
        line += f"  —  {detail}"
    print(line)


def stage(name: str) -> None:
    print(f"\n=== {name} ===")


def step_compileall() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(ROOT)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        log("compileall (every .py compiles)", "FAIL", (exc.stderr or exc.stdout)[:400])
        return False
    log("compileall (every .py compiles)", "PASS", "all modules parse + compile")
    return True


def step_imports() -> bool:
    mods = [
        "config", "llm_client", "enrichment", "email_engine", "crm",
        "internal_intent", "pipeline", "scoring", "intent_engine",
        "reply_classification", "role_suggestions", "outreach", "walego",
        "dashboard_metrics", "nocodb_client", "social_intent", "user_geo",
    ]
    try:
        for m in mods:
            __import__(m)
    except Exception as exc:
        log("imports (every project module)", "FAIL", f"{exc!r}")
        traceback.print_exc()
        return False
    # openrouter_client must NOT exist anymore
    try:
        __import__("openrouter_client")
        log("openrouter_client removed", "FAIL", "module still importable")
        return False
    except ModuleNotFoundError:
        pass
    log("imports (every project module)", "PASS", f"{len(mods)} modules + openrouter_client gone")
    return True


def step_provider_order() -> bool:
    from llm_client import _llm_provider_order
    order = _llm_provider_order()
    if "openrouter" in order:
        log("LLM provider order", "FAIL", f"openrouter still in default: {order}")
        return False
    if order[:2] != ["anthropic", "openai"]:
        log("LLM provider order", "WARN", f"unexpected order: {order}")
        return True
    log("LLM provider order", "PASS", " → ".join(order))
    return True


def step_policy_gates() -> bool:
    import pandas as pd
    from enrichment import waterfall_enrichment, lead_has_verified_contact, CONTACT_PENDING_STATUS
    from email_engine import build_email_sequence
    from crm import seed_crm_from_enriched, merge_seed_with_existing, apply_dispatch_to_records
    from config import LEAD_STATUS_AWAITING_VERIFIED_CONTACT, CONTACT_FABRICATION_DISABLED, allow_synthetic_intent_corpus
    from llm_client import LLMError, generate_enriched_contact_with_llm

    assert CONTACT_FABRICATION_DISABLED is True
    log("policy: CONTACT_FABRICATION_DISABLED", "PASS", "True (cannot be flipped via env)")

    assert allow_synthetic_intent_corpus() is False
    log("policy: synthetic intent corpus", "PASS", "OFF by default (verified live boards only)")

    # AI contact generation must hard-error
    try:
        generate_enriched_contact_with_llm("Acme", "hiring")
    except LLMError as exc:
        log("policy: AI contact generation refused", "PASS", str(exc)[:80])
    else:
        log("policy: AI contact generation refused", "FAIL", "function returned a value!")
        return False

    # Verified-only enrichment dataframe
    scored = pd.DataFrame([
        {"Company": "AcmeCo", "Intent reason": "3 SDR roles", "Intent tier": "High", "Intent score": 92.0, "Role": "SDR"},
        {"Company": "BetaCorp", "Intent reason": "2 AE roles", "Intent tier": "Medium", "Intent score": 70.0, "Role": "Account Executive"},
    ])
    le = waterfall_enrichment(scored)
    for col in ("Name", "Email", "Phone", "LinkedIn"):
        if not (le[col] == "").all():
            log(f"policy: {col} blank in enrichment", "FAIL", "AI contact data leaked!")
            return False
    if not (le["Contact status"] == CONTACT_PENDING_STATUS).all():
        log("policy: contact status", "FAIL", "missing Awaiting verified contact")
        return False
    if not (le["Enrichment verified"] == False).all():  # noqa: E712
        log("policy: Enrichment verified flag", "FAIL", "not all False")
        return False
    log("policy: contacts blank + status set", "PASS", f"{len(le)} rows, all contact cols empty")

    # Email greeting must be generic when name is unverified
    seq = build_email_sequence(le.iloc[0])
    if "Hi there," not in seq[0]["body"]:
        log("policy: deterministic greeting", "FAIL", "Hi there, missing")
        return False
    log("policy: deterministic greeting (no name)", "PASS", "Hi there, in body")

    # CRM seeding holds the row
    records = seed_crm_from_enriched(le, "SDR Team", set())
    for r in records:
        if r["lead_status"] != LEAD_STATUS_AWAITING_VERIFIED_CONTACT or not r["sequence_paused"]:
            log("policy: CRM hold", "FAIL", f"{r['company']} not held")
            return False
    log("policy: CRM holds unverified rows", "PASS", f"{len(records)} rows paused")

    # Dedup is stable across re-runs
    merged = merge_seed_with_existing(records, records)
    if len(merged) != len(records):
        log("policy: merge dedup", "FAIL", f"got {len(merged)} expected {len(records)}")
        return False
    log("policy: merge_seed_with_existing dedup", "PASS", "company key works for blank emails")

    # Dispatch never credits unverified rows
    post = apply_dispatch_to_records(records, {"": 5})
    for r in post:
        if r["touches_sent"] != 0:
            log("policy: dispatch gate", "FAIL", "unverified row credited")
            return False
    log("policy: dispatch gate", "PASS", "blank-email touches ignored")
    return True


def step_live_listings() -> bool:
    """Hit the actual jobspy scraper. Pulls a small sample from Indeed."""
    try:
        from jobspy import scrape_jobs
    except Exception as exc:
        log("live listings", "SKIP", f"python-jobspy not importable: {exc}")
        return True

    print("    fetching live sales listings from Indeed (USA, last 21 days)…")
    t0 = time.time()
    try:
        df = scrape_jobs(
            site_name=["indeed"],
            search_term="sales development representative",
            location="United States",
            results_wanted=15,
            hours_old=24 * 21,
            country_indeed="usa",
        )
    except Exception as exc:
        log("live listings (jobspy.indeed)", "FAIL", f"{exc}")
        traceback.print_exc()
        return False
    elapsed = time.time() - t0
    n = 0 if df is None else len(df)
    if n == 0:
        log("live listings (jobspy.indeed)", "WARN", f"0 rows in {elapsed:.1f}s — board may be throttling")
        return True
    log("live listings (jobspy.indeed)", "PASS", f"{n} rows in {elapsed:.1f}s")

    # Also push them through our parser so we exercise the pipeline.
    from internal_intent import _run_jobspy_query
    rows = _run_jobspy_query("US", "usa", "United States", 10, "sales development representative")
    log("internal_intent._run_jobspy_query", "PASS" if rows else "WARN", f"{len(rows)} sales-role rows after filter")

    # Print the first few real listings.
    print("\n    --- 5 real listings from Indeed ---")
    sample = df.head(5)
    for i, row in sample.iterrows():
        company = (row.get("company") or row.get("company_name") or "").strip()
        title = (row.get("title") or "").strip()
        loc = (row.get("location") or row.get("job_location") or "").strip()
        url = (row.get("job_url") or row.get("url") or "").strip()
        date = str(row.get("date_posted") or "")[:10]
        print(f"    {i + 1}. {company} — {title}")
        print(f"       {loc}  ·  posted {date or 'n/a'}")
        print(f"       {url}")
    print()
    return True


def step_llm_ping() -> bool:
    """Optional: ping Claude + OpenAI directly if keys are configured."""
    from llm_client import LLMError, _anthropic_provider_chat, _openai_provider_chat
    msgs = [{"role": "user", "content": "Reply with exactly the single word: pong"}]
    results = []

    for name, fn in (("anthropic", _anthropic_provider_chat), ("openai", _openai_provider_chat)):
        try:
            out = fn(msgs, 0.0, "default").strip()
        except LLMError as exc:
            log(f"LLM ping ({name})", "SKIP", str(exc)[:120])
            results.append(False)
            continue
        except Exception as exc:
            log(f"LLM ping ({name})", "FAIL", str(exc)[:120])
            results.append(False)
            continue
        if "pong" in out.lower():
            log(f"LLM ping ({name})", "PASS", out[:80])
            results.append(True)
        else:
            log(f"LLM ping ({name})", "WARN", f"unexpected: {out[:80]!r}")
            results.append(True)
    return True


def main() -> int:
    print("IntentEngine — full smoke test")
    print(f"interpreter: {sys.version.split()[0]}")
    print(f"cwd: {ROOT}")

    stage("1. compileall")
    ok = step_compileall()

    stage("2. imports")
    ok = step_imports() and ok

    stage("3. LLM provider order")
    ok = step_provider_order() and ok

    stage("4. verified-only policy gates")
    ok = step_policy_gates() and ok

    stage("5. live job-board listings")
    ok = step_live_listings() and ok

    stage("6. LLM provider ping (Claude + OpenAI)")
    ok = step_llm_ping() and ok

    print("\n=== summary ===")
    pass_n = sum(1 for _, s, _ in REPORT if s == "PASS")
    skip_n = sum(1 for _, s, _ in REPORT if s == "SKIP")
    warn_n = sum(1 for _, s, _ in REPORT if s == "WARN")
    fail_n = sum(1 for _, s, _ in REPORT if s == "FAIL")
    print(f"  PASS={pass_n}  SKIP={skip_n}  WARN={warn_n}  FAIL={fail_n}")
    for step, status, detail in REPORT:
        line = f"    [{status:4}]  {step}"
        if detail:
            line += f"  —  {detail}"
        print(line)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
