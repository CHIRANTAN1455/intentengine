"""In-house enrichment: OpenRouter generates structured (fictional) contact profiles for drafting."""

from __future__ import annotations

import hashlib
import re
import pandas as pd

from openrouter_client import OpenRouterError, generate_enriched_contact_with_openrouter


def _fallback_contact(company: str) -> dict[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "", company.lower())[:20] or "company"
    h = int(hashlib.md5(company.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
    first = ["Alex", "Sam", "Jordan", "Casey"][h % 4]
    last = ["Rivera", "Patel", "Nguyen", "Brooks"][(h // 3) % 4]
    return {
        "first_name": first,
        "last_name": last,
        "title": "Head of Sales",
        "email": f"{first.lower()}.{last.lower()}@{slug}.example.com",
        "linkedin_url": f"https://linkedin.com/in/{first.lower()}-{last.lower()}-{slug}",
        "phone": "",
    }


def waterfall_enrichment(company_or_leads: pd.DataFrame) -> pd.DataFrame:
    if company_or_leads.empty:
        return company_or_leads
    if "Company" not in company_or_leads.columns:
        return company_or_leads

    rows: list[dict] = []
    for _, r in company_or_leads.iterrows():
        company = str(r.get("Company") or "").strip()
        if not company:
            continue
        intent_reason = str(r.get("Intent reason", "") or "")
        try:
            c = generate_enriched_contact_with_openrouter(company, intent_reason)
        except OpenRouterError:
            c = _fallback_contact(company)

        name = f"{c['first_name']} {c['last_name']}".strip()
        rows.append(
            {
                "Name": name,
                "Title": c.get("title", ""),
                "Company": company,
                "Email": c.get("email", ""),
                "Phone": c.get("phone", ""),
                "LinkedIn": c.get("linkedin_url", ""),
                "Enrichment verified": False,
                "Intent reason": intent_reason or "Hiring for sales; intent signals from in-house corpus",
            }
        )
    return pd.DataFrame(rows)
