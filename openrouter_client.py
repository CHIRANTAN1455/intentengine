"""OpenRouter client utilities for content generation and classification."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import requests

from config import CORPUS_NA_JOB_SHARE, MAX_JOB_POSTING_AGE_DAYS, get_openrouter_settings


class OpenRouterError(RuntimeError):
    """Raised for upstream OpenRouter failures."""


def _chat_completion(messages: list[dict[str, str]], temperature: float) -> str:
    try:
        settings = get_openrouter_settings()
    except Exception as exc:
        raise OpenRouterError(f"OpenRouter settings error: {exc}") from exc
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.http_referer,
        "X-Title": settings.app_title,
    }
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": temperature,
    }

    attempts = 3
    last_err = ""
    retryable_status = {408, 409, 425, 429, 500, 502, 503, 504}
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                settings.base_url,
                headers=headers,
                json=payload,
                timeout=settings.timeout_seconds,
            )
            if response.status_code >= 400:
                body_preview = (response.text or "")[:240]
                err = f"HTTP {response.status_code}: {body_preview}"
                if response.status_code in retryable_status and attempt < attempts:
                    last_err = err
                    time.sleep(0.8 * attempt)
                    continue
                raise OpenRouterError(err)
            body = response.json()
            return (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except OpenRouterError:
            raise
        except Exception as exc:  # nosec - network/provider error capture
            last_err = str(exc)
            if attempt == attempts:
                break
            time.sleep(0.8 * attempt)
    raise OpenRouterError(f"OpenRouter request failed after retries: {last_err}")


def classify_reply_with_openrouter(text: str) -> str:
    """Return one of: Interested | Not interested | Unsubscribe."""
    prompt = (
        "Classify the following sales email reply into exactly one label: "
        "Interested, Not interested, or Unsubscribe. "
        "Reply only with JSON like {\"label\": \"Interested\"}.\n\n"
        f"Reply text: {text}"
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "You are a strict classifier. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    try:
        parsed: dict[str, Any] = json.loads(content)
        label = str(parsed.get("label", "")).strip()
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Invalid JSON classification response: {content}") from exc
    if label not in {"Interested", "Not interested", "Unsubscribe"}:
        raise OpenRouterError(f"Unexpected classification label: {label}")
    return label


def generate_email_sequence_with_openrouter(
    lead_context: dict[str, str], max_emails: int
) -> list[dict[str, str]]:
    """Generate outreach sequence as JSON list of {step, subject, body}."""
    prompt = (
        "Generate a concise outbound sequence in JSON only.\n"
        "Rules: list length equals max_emails; each item has step (int), subject (string), body (string); "
        "professional tone, one CTA, no spammy claims.\n"
        f"max_emails={max_emails}\n"
        f"lead_context={json.dumps(lead_context)}"
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "Return valid JSON only. No markdown fences.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Invalid JSON sequence response: {content}") from exc
    if not isinstance(parsed, list):
        raise OpenRouterError("Email sequence response must be a JSON list.")
    cleaned: list[dict[str, str]] = []
    for idx, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject", "")).strip()
        body = str(item.get("body", "")).strip()
        if not subject or not body:
            continue
        cleaned.append({"step": idx, "subject": subject, "body": body})
    if not cleaned:
        raise OpenRouterError("No valid email sequence generated.")
    return cleaned[:max_emails]


def suggest_role_strategy_with_openrouter(role_context: dict[str, str]) -> dict[str, str]:
    """Return role strategy JSON with angle, value_prop, cta, subject_hook."""
    prompt = (
        "You are a B2B outbound strategist. Return JSON only with keys: "
        "angle, value_prop, cta, subject_hook. Keep each under 20 words.\n"
        f"role_context={json.dumps(role_context)}"
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "Return valid JSON only. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Invalid JSON role strategy response: {content}") from exc
    out = {
        "angle": str(parsed.get("angle", "")).strip(),
        "value_prop": str(parsed.get("value_prop", "")).strip(),
        "cta": str(parsed.get("cta", "")).strip(),
        "subject_hook": str(parsed.get("subject_hook", "")).strip(),
    }
    if not all(out.values()):
        raise OpenRouterError(f"Incomplete role strategy response: {out}")
    return out


def _geo_block_for_corpus(geo_hint: dict[str, Any] | None) -> str:
    pct = int(round(100 * CORPUS_NA_JOB_SHARE))
    g = geo_hint or {}
    summary = str(g.get("summary") or "Viewer location unknown; use major US and Canadian tech hubs.")
    in_na = bool(g.get("in_na"))
    city = str(g.get("city") or "")
    region = str(g.get("region") or "")
    cc = str(g.get("countryCode") or "")
    lines = [
        "Geography:",
        f"- About {pct}% of jobs must be for companies headquartered or hiring in the **United States** or **Canada** (realistic company names and metros).",
        f"- At most about {100 - pct}% of jobs may be outside US/Canada (other regions).",
        f"- Viewer context (IP-derived, approximate): {summary}",
    ]
    if in_na and (city or region):
        lines.append(
            f"- Within US/Canada, bias locations toward the viewer's area when plausible: {city}, {region}, {cc}."
        )
    elif not in_na and cc:
        lines.append(
            "- The viewer is outside US/Canada; still keep the US+Canada job share as above (North American GTM hiring demand)."
        )
    lines.append(
        '- Every job must include "countryCode": "US" or "CA" (or occasionally another ISO-3166 alpha-2 for the small non-NA share).'
    )
    lines.append(
        "- Social rows should reference the same companies / hiring motion; keep geography consistent with the jobs."
    )
    return "\n".join(lines) + "\n"


def generate_intent_corpus_with_openrouter(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Generate synthetic-but-structured hiring intent data for the in-house pipeline.
    Returns JSON object: { "jobs": [...], "social": [...] }.
    """
    prompt = (
        "Return JSON only with this shape:\n"
        "{\n"
        '  "jobs": [\n'
        "    {\n"
        '      "companyName": "string",\n'
        '      "title": "string (sales hiring role)",\n'
        '      "url": "https://example.com/job/1",\n'
        '      "postedAt": "YYYY-MM-DD",\n'
        '      "countryCode": "US",\n'
        '      "source": "inhouse"\n'
        "    }\n"
        "  ],\n"
        '  "social": [\n'
        "    {\n"
        '      "companyName": "string",\n'
        '      "text": "string (mentions hiring sales / scaling outbound)",\n'
        '      "source": "inhouse"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Constraints:\n"
        "- Provide 8-12 jobs across 4-6 companies.\n"
        "- Provide 6-10 social rows across overlapping companies.\n"
        "- Titles must include sales roles (SDR, BDR, AE, Account Executive, Sales Rep).\n"
        "- Keep URLs plausible but fictional.\n"
        f"- Every postedAt must be on or after { (date.today() - timedelta(days=MAX_JOB_POSTING_AGE_DAYS)).isoformat() } "
        f"(within the last {MAX_JOB_POSTING_AGE_DAYS} days); no stale listings.\n"
        + _geo_block_for_corpus(geo_hint)
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "Return valid JSON only. No markdown fences."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.55,
    )
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Invalid JSON intent corpus: {content}") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError("Intent corpus must be a JSON object.")
    jobs = parsed.get("jobs")
    social = parsed.get("social")
    if not isinstance(jobs, list) or not isinstance(social, list):
        raise OpenRouterError("Intent corpus jobs/social must be JSON arrays.")
    return {"jobs": jobs, "social": social}


def generate_enriched_contact_with_openrouter(company: str, intent_reason: str) -> dict[str, str]:
    """Generate a plausible decision-maker profile for outreach drafting (not verified)."""
    prompt = (
        "Return JSON only with keys: first_name, last_name, title, email, linkedin_url, phone.\n"
        "Rules:\n"
        "- Email must be fictional (use example.com or companyname.com style), not a real person's inbox.\n"
        "- Title should be a plausible hiring leader for sales hiring.\n"
        "- linkedin_url should be plausible but fictional.\n"
        f"company={json.dumps(company)}\n"
        f"intent_reason={json.dumps(intent_reason)}\n"
    )
    content = _chat_completion(
        [
            {"role": "system", "content": "Return valid JSON only. No markdown fences."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.35,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Invalid JSON contact response: {content}") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError("Contact response must be a JSON object.")
    out = {k: str(parsed.get(k, "") or "").strip() for k in ("first_name", "last_name", "title", "email", "linkedin_url", "phone")}
    if not out["first_name"] or not out["last_name"] or not out["email"]:
        raise OpenRouterError("Incomplete contact JSON.")
    return out
