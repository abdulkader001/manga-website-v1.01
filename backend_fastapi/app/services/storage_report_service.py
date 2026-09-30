"""Storage usage report and alert threshold (roadmap item 12).

Self-hosted chapter pictures grow with the library. This reports how much the
stored pictures take (from ``chapters.pages_bytes``, so no directory walk),
which series take the most, and how full the volume they live on is. The
volume alert threshold is ``STORAGE_ALERT_PERCENT`` (default 80). An optional
``STORAGE_ALERT_BYTES`` also alerts when the pictures alone pass a size.
The same numbers are exported as Prometheus gauges.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Chapter, Manga

try:  # pragma: no cover - prometheus_client is a pinned dependency
    from prometheus_client import Gauge

    _PICTURE_BYTES = Gauge("storage_picture_bytes", "Bytes of stored chapter pictures")
    _VOLUME_USED = Gauge("storage_volume_used_percent", "Used percent of the pictures volume")
except Exception:  # pragma: no cover
    _PICTURE_BYTES = _VOLUME_USED = None

TOP_SERIES = 10


def alert_percent() -> float:
    try:
        return float(os.getenv("STORAGE_ALERT_PERCENT", "80"))
    except ValueError:
        return 80.0


def alert_bytes() -> int:
    try:
        return max(0, int(os.getenv("STORAGE_ALERT_BYTES", "0")))
    except ValueError:
        return 0


def build_report(db: Session) -> Dict[str, Any]:
    from .page_image_service import pages_dir

    total = int(db.query(func.coalesce(func.sum(Chapter.pages_bytes), 0)).scalar() or 0)
    stored_chapters = (
        db.query(func.count(Chapter.id)).filter(Chapter.pages_bytes.isnot(None)).scalar() or 0
    )
    top = (
        db.query(Manga.id, Manga.title, func.sum(Chapter.pages_bytes).label("bytes"))
        .join(Chapter, Chapter.manga_id == Manga.id)
        .filter(Chapter.pages_bytes.isnot(None))
        .group_by(Manga.id, Manga.title)
        .order_by(func.sum(Chapter.pages_bytes).desc())
        .limit(TOP_SERIES)
        .all()
    )
    usage = shutil.disk_usage(pages_dir())
    used_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0

    reasons = []
    if used_percent >= alert_percent():
        reasons.append(f"the volume is {used_percent}% full (limit {alert_percent():g}%)")
    if alert_bytes() and total >= alert_bytes():
        reasons.append(f"pictures use {total} bytes (limit {alert_bytes()})")

    if _PICTURE_BYTES is not None:
        _PICTURE_BYTES.set(total)
        _VOLUME_USED.set(used_percent)

    return {
        "picture_bytes": total,
        "stored_chapters": int(stored_chapters),
        "top_series": [
            {"id": row.id, "title": row.title, "bytes": int(row.bytes or 0)} for row in top
        ],
        "volume": {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": used_percent,
        },
        "alert": {"active": bool(reasons), "reasons": reasons, "percent_limit": alert_percent()},
    }
