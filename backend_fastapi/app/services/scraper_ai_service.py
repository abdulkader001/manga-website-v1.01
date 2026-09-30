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

import os
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
    secret = os.getenv("INTEGRATIONS_SECRET")
    if not secret:
        return None
    try:
        from .integration_key_vault import IntegrationKeyVault

        return IntegrationKeyVault.from_secret(secret)
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
        if not config["api_url"]:
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


def generate_selectors(html_content: str, type: str) -> Optional[Dict[str, str]]:
    """Ask the configured AI for extraction selectors. ``None`` when the AI is
    unconfigured or its answer is unusable — callers must then follow the
    honest-failure path (1G.9), never invent selectors."""

    import json

    config = get_config()
    if config is None:
        return None

    keys_prompt = (
        '"manga_title": "selector", "manga_description": "selector", '
        '"manga_cover": "selector", "chapter_list": "selector", '
        '"chapter_url": "selector", "chapter_title": "selector", '
        '"chapter_number": "selector"'
        if type == "manga"
        else '"page_images": "selector"'
    )
    what = (
        "manga information (title, description, cover image, chapter list "
        "elements, chapter URLs, chapter titles, chapter numbers)"
        if type == "manga"
        else "chapter page images"
    )
    prompt = (
        "You are an expert at web scraping. Given the following simplified "
        f"HTML, determine the best CSS selectors for extracting {what}.\n"
        "Return a strict JSON object with these keys:\n"
        "{\n  " + keys_prompt + "\n}\n\nHTML:\n" + html_content
    )

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
    try:
        parsed = json.loads(content)
    except ValueError:
        logger.warning("scraper_ai_returned_non_json")
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    return {str(k): str(v) for k, v in parsed.items()}
