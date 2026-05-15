"""LLM client for IntentEngine — Anthropic Claude + OpenAI direct only.

OpenRouter has been removed from the codebase. All LLM calls route through:
  1. Anthropic Claude (primary)  — via ANTHROPIC_API_KEY
  2. OpenAI                       — via OPENAI_API_KEY (fallback)

Public API:
    LLMError                       — raised when every configured provider fails
    chat_completion(...)           — low-level chat call
    classify_reply_with_llm(...)   — Interested / Not interested / Unsubscribe
    generate_email_sequence_with_llm(...)
    suggest_role_strategy_with_llm(...)
    generate_intent_corpus_with_llm(...)
    generate_enriched_contact_with_llm(...)  — intentionally disabled, raises
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import requests

from app_secrets import lookup_str as _lookup_str
from config import (
    CORPUS_CA_JOB_SHARE,
    CORPUS_US_JOB_SHARE,
    INTENT_CORPUS_MAX_JOBS,
    INTENT_CORPUS_MIN_JOBS,
    MAX_JOB_POSTING_AGE_DAYS,
    _read_optional_env,
)


class LLMError(RuntimeError):
    """All configured LLM providers (Anthropic, OpenAI) failed."""


_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _llm_timeout_seconds(task: str) -> int:
    if task == "corpus":
        raw = _read_optional_env("LLM_CORPUS_TIMEOUT_SECONDS", "180")
    else:
        raw = _read_optional_env("LLM_TIMEOUT_SECONDS", "30")
    try:
        return max(10, int(raw))
    except ValueError:
        return 180 if task == "corpus" else 30


def _llm_provider_order() -> list[str]:
    """Default order: Anthropic (Claude) first, then OpenAI.

    Operators can override with ``LLM_PROVIDER_ORDER=openai,anthropic`` etc.
    Unknown providers are silently dropped.
    """
    raw = _read_optional_env("LLM_PROVIDER_ORDER", "anthropic,openai")
    aliases = {"chatgpt": "openai", "gpt": "openai", "claude": "anthropic"}
    valid = {"anthropic", "openai"}
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        provider = aliases.get(p, p)
        if provider not in valid or provider in seen:
            continue
        seen.add(provider)
        out.append(provider)
    return out or ["anthropic", "openai"]


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


# --- OpenAI ---------------------------------------------------------------

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
        raw_mt = _read_optional_env("OPENAI_MAX_TOKENS", "1024") or "1024"
        try:
            payload["max_tokens"] = max(16, min(int(raw_mt), 8192))
        except ValueError:
            payload["max_tokens"] = 1024
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


# --- Anthropic Claude -----------------------------------------------------

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
    """Claude takes ``system`` as a top-level field, not as a message role."""
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
        model = _read_optional_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
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


# --- Router ---------------------------------------------------------------

def chat_completion(
    messages: list[dict[str, str]],
    temperature: float,
    *,
    task: str = "default",
) -> str:
    """Route a chat completion through the configured providers in order."""
    errors: list[str] = []
    for provider in _llm_provider_order():
        try:
            if provider == "anthropic":
                return _anthropic_provider_chat(messages, temperature, task)
            if provider == "openai":
                return _openai_provider_chat(messages, temperature, task)
            errors.append(f"unknown provider: {provider}")
        except LLMError as exc:
            errors.append(str(exc))
            continue
    raise LLMError(" | ".join(errors) if errors else "no LLM providers configured")


def _chat(messages: list[dict[str, str]], temperature: float) -> str:
    return chat_completion(messages, temperature, task="default")


def _chat_corpus(messages: list[dict[str, str]], temperature: float) -> str:
    return chat_completion(messages, temperature, task="corpus")


# --- Public task helpers --------------------------------------------------

def classify_reply_with_llm(text: str) -> str:
    """Return one of: Interested | Not interested | Unsubscribe."""
    prompt = (
        "Classify the following sales email reply into exactly one label: "
        "Interested, Not interested, or Unsubscribe. "
        "Reply only with JSON like {\"label\": \"Interested\"}.\n\n"
        f"Reply text: {text}"
    )
    content = _chat(
        [
            {"role": "system", "content": "You are a strict classifier. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    try:
        parsed: dict[str, Any] = json.loads(content)
        label = str(parsed.get("label", "")).strip()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON classification response: {content}") from exc
    if label not in {"Interested", "Not interested", "Unsubscribe"}:
        raise LLMError(f"Unexpected classification label: {label}")
    return label


def generate_email_sequence_with_llm(
    lead_context: dict[str, str], max_emails: int
) -> list[dict[str, str]]:
    """Generate outreach sequence as JSON list of {step, subject, body}.

    Strict guardrail: never invent a contact's name. If
    ``lead_context["has_verified_name"] != "true"`` the model is instructed to
    use a neutral ``"Hi there,"`` greeting.
    """
    prompt = (
        "Generate a concise outbound sequence in JSON only.\n"
        "Rules: list length equals max_emails; each item has step (int), "
        "subject (string), body (string); professional tone, one CTA, no spammy claims.\n"
        "Do not mention LinkedIn, profile views, or any social URLs — contact data is draft-only.\n"
        "CRITICAL: never invent a recipient's name. If has_verified_name is "
        "'false' (or missing), greet with 'Hi there,' and do NOT use a first or last name.\n"
        f"max_emails={max_emails}\n"
        f"lead_context={json.dumps(lead_context)}"
    )
    content = _chat(
        [
            {
                "role": "system",
                "content": (
                    "Return valid JSON only. No markdown fences. Never include LinkedIn "
                    "URLs or claims of having viewed a profile. Never fabricate a "
                    "recipient name, email, or phone number."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON sequence response: {content}") from exc
    if not isinstance(parsed, list):
        raise LLMError("Email sequence response must be a JSON list.")
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
        raise LLMError("No valid email sequence generated.")
    return cleaned[:max_emails]


def suggest_role_strategy_with_llm(role_context: dict[str, str]) -> dict[str, str]:
    """Return role strategy JSON with angle, value_prop, cta, subject_hook."""
    prompt = (
        "You are a B2B outbound strategist. Return JSON only with keys: "
        "angle, value_prop, cta, subject_hook. Keep each under 20 words.\n"
        f"role_context={json.dumps(role_context)}"
    )
    content = _chat(
        [
            {"role": "system", "content": "Return valid JSON only. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON role strategy response: {content}") from exc
    out = {
        "angle": str(parsed.get("angle", "")).strip(),
        "value_prop": str(parsed.get("value_prop", "")).strip(),
        "cta": str(parsed.get("cta", "")).strip(),
        "subject_hook": str(parsed.get("subject_hook", "")).strip(),
    }
    if not all(out.values()):
        raise LLMError(f"Incomplete role strategy response: {out}")
    return out


# --- Intent corpus (opt-in only; gated by ALLOW_SYNTHETIC_INTENT_CORPUS) ---

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
    lines.append('- Every job must include "countryCode" and use only "CA" or "US".')
    lines.append(
        "- Social rows should reference the same companies / hiring motion; keep geography consistent with the jobs."
    )
    return "\n".join(lines) + "\n"


def generate_intent_corpus_with_llm(geo_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Structured hiring intent data (LLM fallback). Returns {"jobs":[], "social":[]}.

    Note: this is only invoked when ``ALLOW_SYNTHETIC_INTENT_CORPUS=1`` and is
    therefore off by default in production.
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
        '      "listingSnippet": "string: 2-4 sentences mirroring the real posting summary"\n'
        "    }\n"
        "  ],\n"
        '  "social": [\n'
        '    {"companyName": "string", "text": "string", "source": "linkedin|twitter|news|other"}\n'
        "  ]\n"
        "}\n"
        "Hard rules:\n"
        f"- Provide {INTENT_CORPUS_MIN_JOBS}-{INTENT_CORPUS_MAX_JOBS} jobs across many distinct companies.\n"
        "- Provide 30-60 social rows referencing overlapping companies.\n"
        "- Each url must be a real https URL pattern from public boards or ATS/careers pages.\n"
        "- Never use example.com, localhost, or obviously fake hosts.\n"
        f"- Every postedAt must be on or after {(date.today() - timedelta(days=MAX_JOB_POSTING_AGE_DAYS)).isoformat()} "
        f"(within the last {MAX_JOB_POSTING_AGE_DAYS} days).\n"
        + _geo_block_for_corpus(geo_hint)
    )
    content = _chat_corpus(
        [
            {
                "role": "system",
                "content": (
                    "You are a senior labor-market researcher. Return valid JSON only, no markdown fences. "
                    "Use real listing patterns and concrete locations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.38,
    )
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON intent corpus: {content}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Intent corpus must be a JSON object.")
    jobs = parsed.get("jobs")
    social = parsed.get("social")
    if not isinstance(jobs, list) or not isinstance(social, list):
        raise LLMError("Intent corpus jobs/social must be JSON arrays.")
    return {"jobs": jobs, "social": social}


def generate_enriched_contact_with_llm(company: str, intent_reason: str) -> dict[str, str]:
    """Deprecated and intentionally disabled.

    AI contact generation is permanently off. Contact data must come from a
    verified provider (Apollo, Hunter, ZoomInfo, etc.) or remain blank.
    Any caller that imports this will get an LLMError so fabricated rows can
    never accidentally enter the pipeline again.
    """
    raise LLMError(
        "AI contact generation is disabled. Use a verified data source or "
        "return blank contact fields."
    )
