"""Cache administration (SRS 2C.4): Mechanism A (platform default caching)
and the admin actions that manage the shared cache's contents.

Mechanism A and Mechanism B (2C.4.4, a user's own "share my translations"
toggle) are deliberately separate, non-overlapping controls (2C.4.2):
Mechanism A only ever affects whether OTHER READERS are served from the
cache by default; it can never stop an individual user's own opted-in
contribution. This module owns Mechanism A and the admin-only clear/
refresh/statistics actions; ``processing_settings_service``/
``UserProcessingSettings.share_translations`` owns Mechanism B.
"""

from __future__ import annotations

import random
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Chapter, Manga, OcrCache, SystemSettings, TranslationCache
from .system_settings_service import get_or_create_system_settings

CACHE_PRIORITY_ON = "on"
CACHE_PRIORITY_REDUCED = "reduced"
CACHE_PRIORITY_OFF = "off"
CACHE_PRIORITIES = (CACHE_PRIORITY_ON, CACHE_PRIORITY_REDUCED, CACHE_PRIORITY_OFF)

# 2C.4.3 "Reduced": lower selection weight so a larger share of requests
# produce fresh translations even when a cached one exists.
REDUCED_CACHE_HIT_PROBABILITY = 0.5

SCOPE_ALL = "all"
SCOPE_SERIES = "series"
SCOPE_WEBSITE = "website"
SCOPES = (SCOPE_ALL, SCOPE_SERIES, SCOPE_WEBSITE)


class CacheAdminError(ValueError):
    pass


def _settings(db: Session) -> SystemSettings:
    return get_or_create_system_settings(db)


def get_cache_priority(db: Session) -> str:
    return _settings(db).cache_priority or CACHE_PRIORITY_ON


def set_cache_priority(db: Session, value: str) -> str:
    value = (value or "").strip().lower()
    if value not in CACHE_PRIORITIES:
        raise CacheAdminError(f"cache_priority must be one of {CACHE_PRIORITIES}")
    settings = _settings(db)
    settings.cache_priority = value
    db.commit()
    return value


def should_check_cache(
    cache_priority: str, *, reader_requested_cached: bool = False
) -> bool:
    """Mechanism A: whether THIS read should try the shared cache first.

    Never touches Mechanism B -- a user's own opted-in contribution is
    written regardless of this decision (see cache_write_should_share()).
    """

    if cache_priority == CACHE_PRIORITY_OFF:
        return reader_requested_cached
    if cache_priority == CACHE_PRIORITY_REDUCED:
        return random.random() < REDUCED_CACHE_HIT_PROBABILITY
    return True


def _chapter_ids_for_manga(db: Session, manga_id: int) -> list[int]:
    return [
        row[0]
        for row in db.query(Chapter.id).filter(Chapter.manga_id == manga_id).all()
    ]


def _chapter_ids_for_website(db: Session, domain: str) -> list[int]:
    domain = domain.strip().lower()
    manga_ids = []
    for manga_id, source_url in db.query(Manga.id, Manga.source_url).all():
        if not source_url:
            continue
        hostname = (urlparse(source_url).hostname or "").lower()
        if hostname == domain or hostname.endswith(f".{domain}"):
            manga_ids.append(manga_id)
    if not manga_ids:
        return []
    return [
        row[0]
        for row in db.query(Chapter.id).filter(Chapter.manga_id.in_(manga_ids)).all()
    ]


def _resolve_chapter_ids(
    db: Session, *, scope: str, manga_id: Optional[int], domain: Optional[str]
) -> Optional[list[int]]:
    """Return chapter ids to scope to, or None for "all" (no filter)."""

    if scope == SCOPE_ALL:
        return None
    if scope == SCOPE_SERIES:
        if not manga_id:
            raise CacheAdminError("manga_id is required for scope=series")
        return _chapter_ids_for_manga(db, manga_id)
    if scope == SCOPE_WEBSITE:
        if not domain:
            raise CacheAdminError("domain is required for scope=website")
        return _chapter_ids_for_website(db, domain)
    raise CacheAdminError(f"scope must be one of {SCOPES}")


def clear_cache(
    db: Session,
    *,
    scope: str,
    manga_id: Optional[int] = None,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """2C.4.3 "Clear cache": purge the shared cache immediately, forcing
    regeneration on next read. Never touches a user's private per-user
    override translations (1H.14.6)."""

    chapter_ids = _resolve_chapter_ids(
        db, scope=scope, manga_id=manga_id, domain=domain
    )

    tc_query = db.query(TranslationCache)
    oc_query = db.query(OcrCache)
    if chapter_ids is not None:
        if not chapter_ids:
            return {
                "scope": scope,
                "translation_rows": 0,
                "ocr_rows": 0,
                "chapters_affected": 0,
            }
        tc_query = tc_query.filter(TranslationCache.chapter_id.in_(chapter_ids))
        oc_query = oc_query.filter(OcrCache.chapter_id.in_(chapter_ids))

    translation_rows = tc_query.delete(synchronize_session=False)
    ocr_rows = oc_query.delete(synchronize_session=False)
    db.commit()

    return {
        "scope": scope,
        "translation_rows": translation_rows,
        "ocr_rows": ocr_rows,
        "chapters_affected": len(chapter_ids) if chapter_ids is not None else None,
    }


def refresh_cache(
    db: Session,
    *,
    scope: str,
    manga_id: Optional[int] = None,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """2C.4.3 "Refresh cache": mark existing entries low-priority without
    deleting them, so new reads produce fresh translations that compete
    with (and can replace) the old ones under quality tiering (1H.14.8),
    rather than an outright purge."""

    chapter_ids = _resolve_chapter_ids(
        db, scope=scope, manga_id=manga_id, domain=domain
    )

    tc_query = db.query(TranslationCache)
    oc_query = db.query(OcrCache)
    if chapter_ids is not None:
        if not chapter_ids:
            return {
                "scope": scope,
                "translation_rows": 0,
                "ocr_rows": 0,
                "chapters_affected": 0,
            }
        tc_query = tc_query.filter(TranslationCache.chapter_id.in_(chapter_ids))
        oc_query = oc_query.filter(OcrCache.chapter_id.in_(chapter_ids))

    # "Free" is the lowest quality tier -- demoting to it lets any
    # subsequent write (even another free-tier one) win under the
    # >=-tier-wins rule in translation_cache_service, rather than requiring
    # a strictly higher tier to ever replace stale content.
    translation_rows = tc_query.update(
        {"quality_tier": "free"}, synchronize_session=False
    )
    ocr_rows = oc_query.update({"quality_tier": "free"}, synchronize_session=False)
    db.commit()

    return {
        "scope": scope,
        "translation_rows": translation_rows,
        "ocr_rows": ocr_rows,
        "chapters_affected": len(chapter_ids) if chapter_ids is not None else None,
    }


def cache_statistics(db: Session) -> Dict[str, Any]:
    """2C.4.3 cache statistics: percentage of reads served from cache vs
    freshly produced. Read/hit counts aren't tracked per-request (that
    would need a separate metrics store); this reports what's directly
    knowable from the cache tables themselves -- size, and how much of it
    is user-contributed (Mechanism B) vs platform-produced -- which is the
    same "how much is the cache carrying the platform" signal 2C.4.1 asks
    the administrator to be able to see.
    """

    total_translations = db.query(func.count(TranslationCache.id)).scalar() or 0
    shared_contributed = (
        db.query(func.count(TranslationCache.id))
        .filter(TranslationCache.contributed_by_sharing.is_(True))
        .scalar()
        or 0
    )
    total_ocr = db.query(func.count(OcrCache.id)).scalar() or 0

    by_language = dict(
        db.query(TranslationCache.target_lang, func.count(TranslationCache.id))
        .group_by(TranslationCache.target_lang)
        .all()
    )

    return {
        "cache_priority": get_cache_priority(db),
        "ocr_cache_entries": total_ocr,
        "translation_cache_entries": total_translations,
        "user_contributed_entries": shared_contributed,
        "platform_produced_entries": total_translations - shared_contributed,
        "entries_by_target_language": by_language,
    }


__all__ = [
    "CacheAdminError",
    "CACHE_PRIORITIES",
    "CACHE_PRIORITY_ON",
    "CACHE_PRIORITY_REDUCED",
    "CACHE_PRIORITY_OFF",
    "SCOPES",
    "SCOPE_ALL",
    "SCOPE_SERIES",
    "SCOPE_WEBSITE",
    "get_cache_priority",
    "set_cache_priority",
    "should_check_cache",
    "clear_cache",
    "refresh_cache",
    "cache_statistics",
]
