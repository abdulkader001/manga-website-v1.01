"""Signed image proxy for source CDNs that refuse hotlinked images.

Some manga CDNs only serve page images when the request carries the source
site's ``Referer`` (e.g. Naver's ``pstatic.net``). For such sources the
chapter payload hands the browser ``/api/v1/images/proxy?u=...&r=...&s=...``
instead of the raw URL; the backend fetches the image with the right
``Referer`` and streams it back.

The URL and referer are HMAC-signed with the server secret, so the endpoint
only ever fetches URLs the backend itself put into a chapter -- it cannot be
used as an open proxy. Every fetch still goes through the SSRF guard.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import List, Optional
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from ..core.settings import settings
from ..models import Chapter

PROXY_PATH = os.getenv("PUBLIC_API_PREFIX", "/api/v1").rstrip("/") + "/images/proxy"
MAX_PROXY_IMAGE_BYTES = 20 * 1024 * 1024


def _key() -> bytes:
    return ("image-proxy:" + (settings.secret_key or "")).encode("utf-8")


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def sign(url: str, referer: str) -> str:
    message = f"{url}\n{referer}".encode("utf-8")
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()[:40]


def proxied_url(url: str, referer: str) -> str:
    query = urlencode({"u": _b64(url), "r": _b64(referer), "s": sign(url, referer)})
    return f"{PROXY_PATH}?{query}"


def decode_request(u: str, r: str, s: str) -> Optional[tuple[str, str]]:
    """Return ``(url, referer)`` when the signature is valid, else ``None``."""

    try:
        url, referer = _unb64(u), _unb64(r)
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(sign(url, referer), s or ""):
        return None
    return url, referer


def _referer_for(chapter: Chapter) -> Optional[str]:
    """The Referer a source requires for its images, from its parser config."""

    from ..scrapers.config import ConfigManager

    page_url = chapter.chapter_url or (chapter.manga.source_url if chapter.manga else "")
    domain = urlparse(page_url or "").netloc
    if not domain:
        return None
    config = ConfigManager.get_config(domain) or {}
    referer = config.get("image_referer")
    if referer == "page":
        return page_url
    if isinstance(referer, str) and referer.startswith(("http://", "https://")):
        return referer
    if config.get("proxy_images"):
        return page_url
    return None


def reader_page_urls(db: Session, chapter: Chapter) -> List[str]:
    """Page image URLs as the browser should load them.

    Our own compressed copies are served as-is (optionally through the image
    CDN); source URLs go through the signed proxy when the source blocks
    hotlinking.
    """

    from ..utils.cdn import build_cdn_url
    from . import page_image_service

    raw = chapter.pages or []
    pages = [p for p in (raw if isinstance(raw, list) else [raw]) if isinstance(p, str) and p]
    referer = _referer_for(chapter) if any(not page_image_service.is_local_url(p) for p in pages) else None
    urls: List[str] = []
    for page in pages:
        if page_image_service.is_local_url(page):
            urls.append(build_cdn_url(page) or page)
        elif referer:
            urls.append(proxied_url(page, referer))
        else:
            urls.append(page)
    return urls
