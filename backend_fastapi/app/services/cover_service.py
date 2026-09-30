"""Series cover images: download once, verify, re-encode to WebP, self-host.

Hotlinking a source's cover breaks when the source changes URLs or blocks
referers, and serving an attacker-supplied file as-is would make the site
host arbitrary bytes. Every cover is fetched through the SSRF-safe client,
size-capped, decoded with Pillow (decompression-bomb safe) and re-encoded, so
what is stored is always a plain WebP raster.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

import structlog

from ..core.settings import settings
from ..utils.image_safety import ImageTooLargeError, InvalidImageError, open_image_safely

logger = structlog.get_logger(__name__)

COVER_URL_PREFIX = os.getenv("PUBLIC_API_PREFIX", "/api/v1").rstrip("/") + "/manga/covers/"
MAX_COVER_BYTES = 8 * 1024 * 1024
MAX_COVER_PIXELS = 30_000_000
MAX_WIDTH, MAX_HEIGHT = 720, 1080
_FILENAME_RE = re.compile(r"^[a-f0-9]{40}\.webp$")


def covers_dir() -> Path:
    configured = os.getenv("COVER_UPLOAD_DIR") or getattr(settings, "cover_upload_dir", None)
    base = Path(configured) if configured else Path(__file__).resolve().parents[3] / "storage" / "covers"
    base.mkdir(parents=True, exist_ok=True)
    return base


def is_valid_filename(name: str) -> bool:
    return bool(_FILENAME_RE.match(name or ""))


def path_for(name: str) -> Optional[Path]:
    if not is_valid_filename(name):
        return None
    target = covers_dir() / name
    return target if target.is_file() else None


def public_url(name: str) -> str:
    return f"{COVER_URL_PREFIX}{name}"


def store_cover_bytes(raw: bytes) -> str:
    """Validate + re-encode ``raw``; returns the public cover URL."""

    image = open_image_safely(raw, max_pixels=MAX_COVER_PIXELS)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((MAX_WIDTH, MAX_HEIGHT))
    from io import BytesIO

    out = BytesIO()
    image.save(out, format="WEBP", quality=82, method=4)
    payload = out.getvalue()
    name = hashlib.sha1(payload).hexdigest() + ".webp"
    target = covers_dir() / name
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(target)
    return public_url(name)


def fetch_and_store(cover_url: Optional[str], *, referer: Optional[str] = None) -> Optional[str]:
    """Download a remote cover and self-host it. ``None`` if it cannot be
    fetched or is not a valid image (the caller keeps the original URL)."""

    if not cover_url or not cover_url.startswith(("http://", "https://")):
        return None

    from ..scrapers.http_client import RequestWrapper

    headers = {"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    try:
        response = RequestWrapper.get(
            cover_url, timeout=20, headers=headers, max_bytes=MAX_COVER_BYTES
        )
        if response.status_code != 200:
            return None
        return store_cover_bytes(response.content)
    except (InvalidImageError, ImageTooLargeError) as exc:
        logger.info("cover_rejected", url=cover_url, reason=str(exc)[:120])
    except Exception as exc:
        logger.info("cover_fetch_failed", url=cover_url, error=str(exc)[:200])
    return None
