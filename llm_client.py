"""
LLM middleware: try OpenAI (ChatGPT) and Anthropic (Claude) APIs directly, then OpenRouter.

Set LLM_PROVIDER_ORDER (comma-separated), e.g. openai,anthropic,openrouter
Configure keys: OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY (each optional; missing providers are skipped).
"""
from __future__ import annotations

import time
from typing import Any

import requests

from config import _lookup_str, _read_optional_env, get_openrouter_settings


class LLMError(RuntimeError):
    """All configured LLM providers failed."""


_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _timeout_seconds() -> int:
    raw = _read_optional_env("OPENROUTER_TIMEOUT_SECONDS", "25")
    try:
        return max(5, int(raw))
    except ValueError:
        return 25


def _provider_order() -> list[str]:
    # Default keeps previous behavior; set LLM_PROVIDER_ORDER=openai,anthropic,openrouter for direct APIs first.
    raw = _read_optional_env("LLM_PROVIDER_ORDER", "openrouter")
    aliases = {"chatgpt": "openai", "gpt": "openai", "claude": "anthropic"}
    out: list[str] = []
    for part in raw.split(","):
        p = part.strip().lower()
        if not p:
            continue
        out.append(aliases.get(p, p))
    return out or ["openrouter"]


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], label: str) -> dict[str, Any]:
    attempts = 3
    last_err = ""
    timeout = _timeout_seconds()
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
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


def _openai_chat(messages: list[dict[str, str]], temperature: float) -> str:
    key = _lookup_str("OPENAI_API_KEY")
    if not key:
        raise LLMError("openai: OPENAI_API_KEY not set")
    model = _read_optional_env("OPENAI_MODEL", "gpt-4o-mini")
    base = _read_optional_env("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
    body = _post_json(
        base,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": model, "messages": messages, "temperature": temperature},
        "openai",
    )
    content = (
        body.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    ).strip()
    if not content:
        raise LLMError("openai: empty content")
    return content


def _anthropic_max_tokens() -> int:
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


def _anthropic_chat(messages: list[dict[str, str]], temperature: float) -> str:
    key = _lookup_str("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("anthropic: ANTHROPIC_API_KEY not set")
    model = _read_optional_env("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
    system, msgs = _anthropic_split_messages(messages)
    if not msgs:
        raise LLMError("anthropic: no user/assistant messages")
    url = _read_optional_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": _anthropic_max_tokens(),
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
    body = _post_json(url, headers, payload, "anthropic")
    blocks = body.get("content") or []
    texts: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            texts.append(str(b.get("text") or ""))
    content = "\n".join(t for t in texts if t).strip()
    if not content:
        raise LLMError("anthropic: empty content")
    return content


def _openrouter_chat(messages: list[dict[str, str]], temperature: float) -> str:
    if not _lookup_str("OPENROUTER_API_KEY"):
        raise LLMError("openrouter: OPENROUTER_API_KEY not set")
    settings = get_openrouter_settings()
    body = _post_json(
        settings.base_url,
        {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.http_referer,
            "X-Title": settings.app_title,
        },
        {"model": settings.model, "messages": messages, "temperature": temperature},
        "openrouter",
    )
    content = (
        body.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    ).strip()
    if not content:
        raise LLMError("openrouter: empty content")
    return content


def chat_completion(messages: list[dict[str, str]], temperature: float) -> str:
    """
    Run chat completion using LLM_PROVIDER_ORDER until one succeeds.
    """
    errors: list[str] = []
    for provider in _provider_order():
        try:
            if provider == "openai":
                return _openai_chat(messages, temperature)
            if provider == "anthropic":
                return _anthropic_chat(messages, temperature)
            if provider == "openrouter":
                return _openrouter_chat(messages, temperature)
            errors.append(f"unknown provider: {provider}")
        except LLMError as exc:
            errors.append(str(exc))
            continue
    raise LLMError(" | ".join(errors) if errors else "no LLM providers configured")
