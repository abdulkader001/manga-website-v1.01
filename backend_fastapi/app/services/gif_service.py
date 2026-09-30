"""GIF Tier 1 (SRS 3B.2): search an external catalogue, store URL/metadata only.

The platform never stores the GIF file itself -- only a reference. If no
catalogue provider is configured, search degrades gracefully to an empty,
clearly-flagged result rather than a hard error.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests
import structlog

logger = structlog.get_logger("backend_fastapi.gif_service")

_TENOR_URL = "https://tenor.googleapis.com/v2/search"


def _api_key() -> str | None:
    return os.getenv("GIF_PROVIDER_API_KEY") or os.getenv("TENOR_API_KEY")


def is_configured() -> bool:
    return bool(_api_key())


def search(query: str, *, limit: int = 20) -> Dict[str, Any]:
    api_key = _api_key()
    if not api_key or not (query or "").strip():
        return {"configured": bool(api_key), "results": []}

    try:
        response = requests.get(
            _TENOR_URL,
            params={
                "q": query.strip(),
                "key": api_key,
                "limit": min(limit, 50),
                "media_filter": "gif",
                "contentfilter": "medium",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # pragma: no cover - network dependent
        logger.warning("gif_search_failed", exc_info=True)
        return {"configured": True, "results": []}

    results: List[Dict[str, Any]] = []
    for item in payload.get("results", []):
        media = (item.get("media_formats") or {}).get("gif") or {}
        url = media.get("url")
        if not url:
            continue
        results.append(
            {
                "provider": "tenor",
                "id": item.get("id"),
                "url": url,
                "width": (media.get("dims") or [None, None])[0],
                "height": (media.get("dims") or [None, None])[1],
                "preview_url": (
                    (item.get("media_formats") or {}).get("tinygif") or {}
                ).get("url"),
                "description": item.get("content_description"),
            }
        )
    return {"configured": True, "results": results}


__all__ = ["is_configured", "search"]
