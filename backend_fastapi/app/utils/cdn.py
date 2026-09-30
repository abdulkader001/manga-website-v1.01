"""CDN URL helpers for media assets."""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urljoin
from typing import Optional


@lru_cache(maxsize=1)
def _cdn_base() -> Optional[str]:
    base = os.getenv("IMAGE_CDN_BASE_URL")
    if not base:
        return None
    return base.rstrip("/") + "/"


def build_cdn_url(path: Optional[str]) -> Optional[str]:
    """Return a CDN-prefixed URL for ``path`` when configured.

    ``path`` may be an absolute URL (in which case it is returned unchanged),
    a relative path (``/covers/foo.jpg``), or ``None``. The helper reads the
    ``IMAGE_CDN_BASE_URL`` environment variable lazily so environments without
    a CDN do not pay unnecessary overhead.
    """

    if not path:
        return path

    if path.startswith("http://") or path.startswith("https://"):
        return path

    base = _cdn_base()
    if not base:
        return path

    return urljoin(base, path.lstrip("/"))


__all__ = ["build_cdn_url"]
