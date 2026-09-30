"""The scraper-creation AI (SRS 1G.8.7 / 1G.8.8).

A dedicated, single-purpose AI whose key the Permanent Administrator supplies
in Admin Panel -> API Management. Its ONLY job is generating and repairing
website parsers; nothing else in the system may call it. The key is stored in
the encrypted ``ProviderCredentials`` vault (same handling as user
credentials), never displayed, never logged.

This module is deliberately the single entry point: ``get_config`` /
``test_connection`` / ``generate_selectors`` are consumed only by the parser
generation path (``scrapers.ai_fallback``) and its admin Test action.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

SERVICE_NAME = "scraper_ai"

# The exact honest-failure statement (SRS 1G.9.2), verbatim.
HONEST_FAILURE_MESSAGE = (
    "Automatic scraper generation cannot reliably create a scraper for this "
    "website from only its homepage URL. It is not theoretically possible to "
    "derive the extraction rules from this URL alone. A website-specific "
    "parser is required."
)

# What to request when generation is not possible (SRS 1G.9.3).
REQUIRED_INPUTS = [
    "A sample series/manga page URL",
    "A sample chapter page URL",
    "Example raw image URLs",
    "A description of how the website is structured",
    "Any site-specific authentication, pagination, or lazy-loading behaviour",
]


def honest_failure_report(domain: str) -> Dict[str, Any]:
    """The 1G.9 report: plain statement + exactly what is needed instead."""

    return {
        "possible": False,
        "domain": domain,
        "message": HONEST_FAILURE_MESSAGE,
        "required_inputs": REQUIRED_INPUTS,
    }


def _vault():
    try:
        from .integration_key_vault import IntegrationKeyVault

        return IntegrationKeyVault.from_env()
    except Exception:  # pragma: no cover - defensive
        return None


def get_config() -> Optional[Dict[str, Any]]:
    """The PA-configured scraper-AI provider, decrypted, or ``None``.

    Reads directly from the encrypted credentials store so it works both in
    the API process and inside Celery workers (which have no app.state).
    """

    from ..core.db import SessionLocal
    from ..models import ProviderCredentials

    with SessionLocal() as session:
        record = (
            session.query(ProviderCredentials)
            .filter_by(provider_name=SERVICE_NAME, is_system=True)
            .one_or_none()
        )
        if record is None or not record.enabled:
            return None
        cfg = record.config or {}
        vault = _vault()
        api_key = record.api_key
        if api_key and vault is not None:
            api_key = vault.decrypt(api_key)
        config = {
            "provider": cfg.get("provider_id") or record.provider or "custom",
            "api_key": api_key,
            "api_url": cfg.get("api_url"),
            "model": cfg.get("model"),
            "headers": cfg.get("headers"),
        }
        if not config["api_url"] and not is_anthropic(config):
            return None
        return config


def is_configured() -> bool:
    return get_config() is not None


def _chat_request(
    config: Dict[str, Any], prompt: str, *, timeout: int = 45
) -> Optional[str]:
    """Provider-neutral single-prompt completion.

    Speaks the OpenAI-compatible chat shape by default and the Gemini
    generateContent shape for Google endpoints — any capable provider plugs in
    by changing the configuration alone (1G.8.8).
    """

    import requests

    api_url = config.get("api_url") or ""
    api_key = config.get("api_key") or ""
    headers = dict(config.get("headers") or {})
    headers.setdefault("Content-Type", "application/json")

    if is_anthropic(config):
        return _anthropic_request(config, prompt, timeout=timeout)

    if "generativelanguage.googleapis.com" in api_url:
        params = {"key": api_key} if api_key else None
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(
            api_url, headers=headers, params=params, json=body, timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts) or None

    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    if config.get("model"):
        body["model"] = config["model"]
    response = requests.post(api_url, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message") or {}).get("content")


ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
# Retired Claude model labels still offered by older admin UIs, mapped onto
# the current model of the same line.
_ANTHROPIC_MODEL_ALIASES = {
    "claude-3-7-sonnet": "claude-sonnet-5-5",
    "claude-3-5-sonnet": "claude-sonnet-5-5",
    "claude-sonnet": "claude-sonnet-5-5",
    "claude-opus": "claude-opus-5-5",
    "claude-haiku": "claude-haiku-4-5",
}


# UI model labels -> the provider's real model id.
_MODEL_ALIASES = {
    "deepseek-r1": "deepseek-reasoner",
    "deepseek-v3": "deepseek-chat",
    "llama-3.3-70b-groq": "llama-3.3-70b-versatile",
    "qwen-2.5-72b": "qwen2.5-72b-instruct",
    "moonshot-v1": "moonshot-v1-128k",
    "glm-4-plus": "glm-4-plus",
    "sonar-reasoning": "sonar-reasoning",
}

# (key-prefix or substring, provider id, chat endpoint, default model)
_PROVIDERS = [
    ("AIzaSy", "google_gemini", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "gemini-2.5-flash"),
    ("sk-ant-", "anthropic", "https://api.anthropic.com/v1/messages", "claude-opus-5-5"),
    ("gsk_", "groq", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
    ("sk-proj-", "openai", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
    ("sk-", "openai", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
]


def build_provider_config(
    api_key: str, model: Optional[str], endpoint_url: Optional[str]
) -> Dict[str, Any]:
    """Provider settings from what the admin form supplies (key, model label,
    optional custom endpoint). Raises ``ValueError`` with a user-facing reason."""

    key = (api_key or "").strip()
    label = (model or "").strip()
    provider = "custom"
    api_url = ""
    default_model = label
    for marker, provider_id, url, default in _PROVIDERS:
        if key.startswith(marker):
            provider, api_url, default_model = provider_id, url, label or default
            break
    if provider == "custom" and label.startswith("claude"):
        provider, api_url = "anthropic", "https://api.anthropic.com/v1/messages"

    resolved_model = _MODEL_ALIASES.get(default_model, default_model)
    if endpoint_url:
        custom = endpoint_url.strip().rstrip("/")
        if not custom.startswith("https://"):
            raise ValueError("The endpoint URL must start with https://")
        api_url = (
            custom
            if custom.endswith("/chat/completions") or ":generateContent" in custom
            else custom + "/chat/completions"
        )
        if provider not in {"anthropic"}:
            provider = provider if provider != "custom" else "custom"
    if not api_url:
        raise ValueError(
            "Could not tell which AI provider this key belongs to. Enter its API endpoint URL too."
        )
    if provider == "anthropic":
        resolved_model = anthropic_model(resolved_model)
    else:
        resolved_model = resolved_model.replace("{model}", "")
    return {
        "provider_id": provider,
        "api_url": api_url.replace("{model}", resolved_model or "gemini-2.5-flash"),
        "model": resolved_model,
    }


def is_anthropic(config: Dict[str, Any]) -> bool:
    provider = str(config.get("provider") or "").lower()
    model = str(config.get("model") or "").lower()
    api_url = str(config.get("api_url") or "").lower()
    return provider in {"anthropic", "claude"} or "anthropic.com" in api_url or model.startswith("claude")


def anthropic_model(model: Optional[str]) -> str:
    name = (model or "").strip()
    if not name:
        return ANTHROPIC_DEFAULT_MODEL
    return _ANTHROPIC_MODEL_ALIASES.get(name, name)


def _anthropic_request(
    config: Dict[str, Any], prompt: str, *, timeout: int = 45
) -> Optional[str]:
    """Claude via the official SDK. A policy decline is retried server-side
    on a fallback model; a final refusal yields ``None`` (honest failure)."""

    import anthropic

    client = anthropic.Anthropic(
        api_key=config.get("api_key") or None,
        timeout=float(timeout),
        max_retries=2,
    )
    response = client.beta.messages.create(
        model=anthropic_model(config.get("model")),
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        logger.warning("scraper_ai_refused")
        return None
    text = "".join(block.text for block in response.content if block.type == "text")
    return text or None


def test_connection(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The admin panel's Test action (1G.8.8): verify the key actually works
    before it is relied on. Never logs or returns the key itself."""

    config = config or get_config()
    if config is None:
        return {"ok": False, "error": "not_configured"}
    try:
        reply = _chat_request(config, "Reply with the single word: ok", timeout=20)
    except Exception as exc:
        # The exception text may embed the URL but never the key (it is sent
        # in headers/params, which requests does not include in str(exc)).
        return {"ok": False, "error": str(exc)[:300]}
    if not reply:
        return {"ok": False, "error": "empty_response"}
    return {"ok": True, "provider": config.get("provider")}


def generate_selectors(
    html_content: str,
    type: str,
    *,
    feedback: Optional[str] = None,
    hints: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Ask the configured AI for extraction selectors. ``None`` when the AI is
    unconfigured or its answer is unusable — callers must then follow the
    honest-failure path (1G.9), never invent selectors.

    The HTML is condensed first (see ``AIFallbackService._simplify_dom``: long
    runs of identical items are collapsed to a few examples, so a 600-chapter
    list still fits). ``feedback`` carries what went wrong when the previous
    answer was tested on the real page, so a retry corrects a specific
    mistake instead of guessing again; ``hints`` carries deterministic
    findings from structure analysis.
    """

    import json

    config = get_config()
    if config is None:
        return None

    from ..scrapers.ai_fallback import AIFallbackService

    condensed = AIFallbackService._simplify_dom(html_content)[
        : AIFallbackService.MAX_HTML_CHARS
    ]

    if type == "manga":
        what = (
            "the series page of a manga website: the series title, description, "
            "cover image, and the list of chapters"
        )
        keys = (
            '  "manga_title": CSS selector of the element holding the series title,\n'
            '  "manga_description": CSS selector of the synopsis,\n'
            '  "manga_cover": CSS selector of the cover <img> (or meta[property=og:image]),\n'
            '  "manga_author": CSS selector matching the author name element(s) (optional),\n'
            '  "manga_genres": CSS selector matching each genre/tag element (optional),\n'
            '  "chapter_list": CSS selector matching EVERY chapter entry, one element per chapter,\n'
            '  "chapter_url": selector, relative to one chapter entry, of the <a> holding its link '
            '(use "a"; if chapter_list already selects the <a> itself, still use "a"),\n'
            '  "chapter_title": selector relative to one entry of its title text,\n'
            '  "chapter_number": selector relative to one entry of the element holding only the '
            "chapter number (omit if there is none; the number is then read from the title)"
        )
    else:
        what = "a chapter reader page of a manga website: the page images of the chapter"
        keys = (
            '  "page_images": CSS selector matching EVERY page image of the chapter, one element '
            "per page (img or amp-img), and nothing else (no logo, avatar, ad or thumbnail),\n"
            '  "image_attr": the attribute holding the real image URL when images are lazy-loaded '
            '(e.g. "data-src"); omit if plain src is correct,\n'
            '  "next_page": selector of the "next page" link ONLY if one chapter is split across '
            "several URLs; otherwise omit"
        )
    prompt = (
        "You write CSS selectors for a web scraper. Below is a condensed copy of "
        f"{what}. Repeated items have been collapsed to a few examples, so write "
        "selectors that match ALL items of that kind, not just the examples shown.\n\n"
        "Rules:\n"
        "- Prefer stable class names and ids. Never use :nth-child, generated/hashed class "
        "names, or absolute paths from <html>.\n"
        "- Use only selectors that exist in the HTML below; do not invent classes.\n"
        "- Return ONLY one JSON object, no prose, with these keys:\n{\n" + keys + "\n}\n"
    )
    if hints:
        prompt += "\nAnalysis hints:\n" + hints + "\n"
    if feedback:
        prompt += "\n" + feedback + "\n"
    prompt += "\nHTML:\n" + condensed

    try:
        content = _chat_request(config, prompt)
    except Exception as exc:
        logger.warning("scraper_ai_request_failed", error=str(exc)[:300])
        return None
    if not content:
        return None

    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    else:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
    try:
        parsed = json.loads(content)
    except ValueError:
        logger.warning("scraper_ai_returned_non_json")
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    return {str(k): str(v) for k, v in parsed.items() if isinstance(v, (str, int, float))}
