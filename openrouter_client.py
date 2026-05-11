"""OpenRouter client utilities for content generation and classification.

Includes inlined LLM routing (OpenAI / Anthropic / OpenRouter) so Streamlit Cloud
does not depend on a separate top-level ``llm_client`` import (avoids KeyError
there in some hosted runtimes).
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import requests

from config import (
    CORPUS_CA_JOB_SHARE,
    CORPUS_US_JOB_SHARE,
    INTENT_CORPUS_MAX_JOBS,
    INTENT_CORPUS_MIN_JOBS,
    MAX_JOB_POSTING_AGE_DAYS,
    _lookup_str,
    _read_optional_env,
    get_openrouter_settings,
)


class LLMError(RuntimeError):
    """All configured LLM providers failed."""


_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _llm_timeout_seconds(task: str) -> int:
    if task == "corpus":
        raw = _read_optional_env("LLM_CORPUS_TIMEOUT_SECONDS", "180")
    else:
        raw = _read_optional_env("OPENROUTER_TIMEOUT_SECONDS", "25")
    try:
        return max(10, int(raw))
    except ValueError:
        return 180 if task == "corpus" else 25


def _llm_provider_order() -> list[str]:
    raw = _read_optional_env("LLM_PROVIDER_ORDER", "openrouter")
    aliases = {"chatgpt": "openai", "gpt": "openai", "claude": "anthropic"}
    out: list[str] = []
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        out.append(aliases.get(p, p))
    return out or ["openrouter"]


def _llm_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    label: str,
    *,
    timeout: int,
) -> dict[str, Any]:
    attempts = 3
    last_err = ""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=max(10, timeout))
            if response.status_code >= 400:
                body_preview = (response.text or "")[:300]
                err = f"{label} HTTP {response.status_code}: {body_preview}"
                if response.status_code in _RETRYABLE and attempt < attempts:
                    last_err = err
                    time.sleep(0.8 * attempt)
                    continue
                raise LLMError(err)
            return response.json()
        except LLMError:
            raise
        except Exception as exc:
            last_err = f"{label}: {exc}"
            if attempt == attempts:
                break
            time.sleep(0.8 * attempt)
    raise LLMError(f"{label} failed after retries: {last_err}")


def _openai_corpus_max_tokens() -> int:
    raw = _read_optional_env("OPENAI_CORPUS_MAX_TOKENS", "16384") or "16384"
    try:
        return max(4096, int(raw))
    except ValueError:
        return 16384


def _openai_provider_chat(messages: list[dict[str, str]], temperature: float, task: str) -> str:
    key = _lookup_str("OPENAI_API_KEY")
    if not key:
        raise LLMError("openai: OPENAI_API_KEY not set")
    if task == "corpus":
        model = _read_optional_env("OPENAI_CORPUS_MODEL", "gpt-4o")
    else:
        model = _read_optional_env("OPENAI_MODEL", "gpt-4o-mini")
    base = _read_optional_env("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if task == "corpus":
        payload["max_tokens"] = _openai_corpus_max_tokens()
    else:
        raw_mt = _read_optional_env("OPENAI_MAX_TOKENS", "512") or "512"
        try:
            payload["max_tokens"] = max(16, min(int(raw_mt), 8192))
        except ValueError:
            payload["max_tokens"] = 512
    body = _llm_post_json(
        base,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
        "openai",
        timeout=_llm_timeout_seconds(task),
    )
    content = (
        body.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    ).strip()
    if not content:
        raise LLMError("openai: empty content")
    return content


def _anthropic_max_tokens(task: str) -> int:
    if task == "corpus":
        raw = _read_optional_env("ANTHROPIC_CORPUS_MAX_TOKENS", "16384") or "16384"
        try:
            return max(4096, int(raw))
        except ValueError:
            return 16384
    raw = _read_optional_env("ANTHROPIC_MAX_TOKENS", "4096") or "4096"
    try:
        return max(256, int(raw))
    except ValueError:
        return 4096


def _anthropic_split_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system_parts: list[str] = []
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role") or "user").strip()
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": "user", "content": content})
    return "\n\n".join(system_parts), out


def _anthropic_provider_chat(messages: list[dict[str, str]], temperature: float, task: str) -> str:
    key = _lookup_str("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("anthropic: ANTHROPIC_API_KEY not set")
    if task == "corpus":
        model = _read_optional_env("ANTHROPIC_CORPUS_MODEL", "claude-3-5-sonnet-20241022")
    else:
        model = _read_optional_env("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
    system, msgs = _anthropic_split_messages(messages)
    if not msgs:
        raise LLMError("anthropic: no user/assistant messages")
    url = _read_optional_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": _anthropic_max_tokens(task),
        "messages": msgs,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": key,
        "anthropic-version": _read_optional_env("ANTHROPIC_API_VERSION", "2023-06-01"),
        "Content-Type": "application/json",
    }
    body = _llm_post_json(url, headers, payload, "anthropic", timeout=_llm_timeout_seconds(task))
    blocks = body.get("content") or []
    texts: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            texts.append(str(b.get("text") or ""))
    content = "\n".join(t for t in texts if t).strip()
    if not content:
        raise LLMError("anthropic: empty content")
    return content


def _openrouter_corpus_max_tokens() -> int:
    raw = _read_optional_env("OPENROUTER_CORPUS_MAX_TOKENS", "16384") or "16384"
    try:
        return max(4096, int(raw))
    except ValueError:
        return 16384


def _openrouter_default_max_tokens() -> int:
    """Cap completion tokens for normal chat calls (OpenRouter bills against max_tokens)."""
    raw = _read_optional_env("OPENROUTER_MAX_TOKENS", "512") or "512"
    try:
        return max(16, min(int(raw), 8192))
    except ValueError:
        return 512


def _openrouter_provider_chat(messages: list[dict[str, str]], temperature: float, task: str) -> str:
    if not _lookup_str("OPENROUTER_API_KEY"):
        raise LLMError("openrouter: OPENROUTER_API_KEY not set")
    settings = get_openrouter_settings()
    model = settings.model
    if task == "corpus":
        override = _read_optional_env("OPENROUTER_CORPUS_MODEL", "")
        if override:
            model = override
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if task == "corpus":
        payload["max_tokens"] = _openrouter_corpus_max_tokens()
    else:
        payload["max_tokens"] = _openrouter_default_max_tokens()
    body = _llm_post_json(
        settings.base_url,
        {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.http_referer,
            "X-Title": settings.app_title,
        },
        payload,
        "openrouter",
        timeout=_llm_timeout_seconds(task),
    )
    content = (
        body.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    ).strip()
    if not content:
        raise LLMError("openrouter: empty content")
    return content


def chat_completion(
    messages: list[dict[str, str]],
    temperature: float,
    *,
    task: str = "default",
) -> str:
    errors: list[str] = []
    for provider in _llm_provider_order():
        try:
            if provider == "openai":
                return _openai_provider_chat(messages, temperature, task)
            if provider == "anthropic":
                return _anthropic_provider_chat(messages, temperature, task)
            if provider == "openrouter":
                return _openrouter_provider_chat(messages, temperature, task)
            errors.append(f"unknown provider: {provider}")
        except LLMError as exc:
            errors.append(str(exc))
            continue
    raise LLMError(" | ".join(errors) if errors else "no LLM providers configured")


class OpenRouterError(RuntimeError):
    """Raised for upstream LLM / OpenRouter failures."""


def _chat_completion(messages: list[dict[str, str]], temperature: float) -> str:
    try:
        return chat_completion(messages, temperature, task="default")
    except LLMError as exc:
        raise OpenRouterError(str(exc)) from exc


def _chat_completion_corpus(messages: list[dict[str, str]], temperature: float) -> str:
    """Large JSON intent corpus: uses task=corpus (stronger models, higher max tokens, longer timeout)."""
    try:
        return chat_completion(messages, temperature, task="corpus")
    except LLMError as exc:
        raise OpenRouterError(str(exc)) from exc


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
        "Do not mention LinkedIn, profile views, or any social URLs — contact data is draft-only.\n"
        f"max_emails={max_emails}\n"
        f"lead_context={json.dumps(lead_context)}"
    )
    content = _chat_completion(
        [
            {
                "role": "system",
                "content": "Return valid JSON only. No markdown fences. Never include LinkedIn URLs or claims of having viewed a profile.",
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
    pct_ca = int(round(100 * CORPUS_CA_JOB_SHARE))
    pct_us = int(round(100 * CORPUS_US_JOB_SHARE))
    g = geo_hint or {}
    summary = str(g.get("summary") or "Viewer location unknown; use major US and Canadian tech hubs.")
    in_na = bool(g.get("in_na"))
    city = str(g.get("city") or "")
    region = str(g.get("region") or "")
    cc = str(g.get("countryCode") or "")
    lines = [
        "Geography:",
        f"- Country mix target: about {pct_ca}% of jobs in **Canada** and {pct_us}% in the **United States**.",
        "- Keep nearly all jobs in Canada/US; avoid other countries unless explicitly needed for diversity.",
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
        '- Every job must include "countryCode" and use only "CA" or "US".'
    )
    lines.append(
        "- Social rows should reference the same companies / hiring motion; keep geography consistent with the jobs."
    )
    return "\n".join(lines) + "\n"


def generate_intent_corpus_with_openrouter(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Structured hiring intent data for the pipeline (LLM fallback when live boards are sparse).
    Prefer real public job-board / ATS URLs and faithful listing detail—not placeholders.
    Returns JSON object: { "jobs": [...], "social": [...] }.
    """
    prompt = (
        "Return JSON only with this shape:\n"
        "{\n"
        '  "jobs": [\n'
        "    {\n"
        '      "companyName": "string (legal employer name)",\n'
        '      "title": "string (sales hiring role: SDR, BDR, AE, etc.)",\n'
        '      "url": "https://... real job posting URL",\n'
        '      "postedAt": "YYYY-MM-DD",\n'
        '      "countryCode": "US" or "CA",\n'
        '      "source": "linkedin|indeed|lever|greenhouse|ashby|workday|careers_site|other",\n'
        '      "location": "City, Region (e.g. Toronto, ON or Austin, TX)",\n'
        '      "listingSnippet": "string: 2-4 sentences mirroring the real posting summary (comp, scope, stack/motion if stated)"\n'
        "    }\n"
        "  ],\n"
        '  "social": [\n'
        "    {\n"
        '      "companyName": "string",\n'
        '      "text": "string (hiring / GTM / outbound motion aligned with that company)",\n'
        '      "source": "linkedin|twitter|news|other"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Hard rules:\n"
        f"- Provide {INTENT_CORPUS_MIN_JOBS}-{INTENT_CORPUS_MAX_JOBS} jobs across many distinct companies.\n"
        "- Provide 30-60 social rows referencing overlapping companies.\n"
        "- Each url must be a real https URL pattern from public boards or ATS/careers pages "
        "(linkedin.com/jobs, indeed.com/viewjob or /rc/clk, jobs.lever.co, boards.greenhouse.io, "
        "jobs.ashbyhq.com, *.myworkdayjobs.com, or an employer careers subdomain). "
        "Never use example.com, localhost, or obviously fake hosts.\n"
        "- Use your strongest retrieval of **currently typical** North American sales listings; "
        "titles and snippets should read like original postings, not generic templates.\n"
        f"- Every postedAt must be on or after { (date.today() - timedelta(days=MAX_JOB_POSTING_AGE_DAYS)).isoformat() } "
        f"(within the last {MAX_JOB_POSTING_AGE_DAYS} days).\n"
        + _geo_block_for_corpus(geo_hint)
    )
    content = _chat_completion_corpus(
        [
            {
                "role": "system",
                "content": (
                    "You are a senior labor-market researcher. Return valid JSON only, no markdown fences. "
                    "Maximize specificity: real-sounding listing copy, concrete locations, and URLs that match "
                    "known public job-board patterns."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.38,
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
        "- linkedin_url must be an empty string \"\". Do not invent profile URLs — they are unsafe and misleading.\n"
        "- phone may be \"\" if unknown; do not fabricate phone numbers.\n"
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
    out["linkedin_url"] = ""
    return out
