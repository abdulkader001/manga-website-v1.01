"""Policy layer for the shared OCR/translation cache (SRS 1H.14).

Data-model + policy only: get/store-with-quality-upgrade and LRU eviction.
Wiring an actual OCR/MT engine to read and populate these caches is Part 2
scope, per the SRS's own note that Part 2 builds the OCR engine and
translation system on top of what Part 1 establishes here.

Provider tier alone used to authorise every write, which meant an
equal-tier submission overwrote whatever was cached without the two texts
ever being compared -- and since all untrusted engines share the single
"free" tier, that was every untrusted submission. Tier is now only a
pre-filter (strictly lower loses, strictly higher skips the expensive
step); ``submission_quality_gate`` decides the rest from the text itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from ..models.translation_cache import (
    QUALITY_TIER_ORDER,
    DEFAULT_QUALITY_TIER,
    OcrCache,
    TranslationCache,
)
from . import submission_quality_gate


def _tier_rank(tier: Optional[str]) -> int:
    return QUALITY_TIER_ORDER.get(tier or DEFAULT_QUALITY_TIER, 0)


def _record_rejection(
    db: Session, existing: Any, decision: submission_quality_gate.GateDecision
) -> None:
    """Persist anything the gate learned about the entry we are keeping.

    A rejected write still teaches us the incumbent's score (the gate may
    have had to compute it) and, for a legacy row written before hashing
    existed, its hash -- so the next submission settles on the cheap path
    instead of paying for the same model call again.
    """

    changed = False
    if existing.quality_score is None and decision.existing_score is not None:
        existing.quality_score = decision.existing_score
        changed = True
    if not existing.text_hash:
        stored = getattr(existing, "text_boxes", None)
        if stored is None:
            stored = getattr(existing, "translated_boxes", None)
        existing.text_hash = submission_quality_gate.compute_text_hash(stored)
        changed = True
    if changed:
        db.commit()
        db.refresh(existing)


def get_ocr_cache(db: Session, chapter_id: int, page_index: int) -> Optional[OcrCache]:
    entry = (
        db.query(OcrCache)
        .filter(OcrCache.chapter_id == chapter_id, OcrCache.page_index == page_index)
        .one_or_none()
    )
    if entry is not None:
        entry.last_accessed_at = datetime.utcnow()
        db.commit()
    return entry


def put_ocr_cache(
    db: Session,
    chapter_id: int,
    page_index: int,
    text_boxes: List[str],
    *,
    quality_tier: str = DEFAULT_QUALITY_TIER,
    provider: Optional[str] = None,
    regions: Optional[List[Dict[str, Any]]] = None,
    detected_language: Optional[str] = None,
    detected_script: Optional[str] = None,
    reading_order_mode: Optional[str] = None,
    engine_tier: Optional[int] = None,
    page_width: Optional[int] = None,
    page_height: Optional[int] = None,
    ai_assisted_regions: Optional[List[int]] = None,
    trusted: bool = True,
    quality_provider_config: Optional[Dict[str, Any]] = None,
    quality_scorer: Optional[Callable[..., Optional[float]]] = None,
    http_post: Callable[..., Any] = requests.post,
) -> OcrCache:
    """Store OCR output, upgrading in place only when it is actually better.

    A lower-tier result never overwrites a higher-tier one already cached;
    it's a no-op that returns the existing (better) entry instead. At equal
    tier -- where every untrusted engine sits -- ``submission_quality_gate``
    compares the submitted text against what is stored and rejects anything
    that isn't an improvement. ``regions`` (2B.6's normalized shape) is
    optional so Part 1 callers that only ever populated ``text_boxes`` keep
    working unchanged.
    """

    existing = (
        db.query(OcrCache)
        .filter(OcrCache.chapter_id == chapter_id, OcrCache.page_index == page_index)
        .one_or_none()
    )
    if existing is not None:
        if _tier_rank(quality_tier) < _tier_rank(existing.quality_tier):
            return existing
        decision = submission_quality_gate.evaluate(
            new_boxes=text_boxes,
            existing_boxes=existing.text_boxes,
            existing_hash=existing.text_hash,
            existing_score=existing.quality_score,
            # No script expectation on the OCR side: the only language a
            # submission could be checked against is one it reports about
            # itself, and holding it to the *stored* language would
            # permanently lock in an earlier run's misdetection. The
            # translation path below has a real external expectation
            # (target_lang) and does apply the check.
            expected_language=None,
            skip_scoring=_tier_rank(quality_tier) > _tier_rank(existing.quality_tier),
            trusted=trusted,
            provider_config=quality_provider_config,
            scorer=quality_scorer,
            http_post=http_post,
        )
        if not decision.accepted:
            _record_rejection(db, existing, decision)
            return existing

        existing.text_boxes = text_boxes
        existing.text_hash = decision.text_hash
        existing.quality_score = decision.new_score
        existing.quality_tier = quality_tier
        existing.provider = provider
        if regions is not None:
            existing.regions = regions
        if detected_language is not None:
            existing.detected_language = detected_language
        if detected_script is not None:
            existing.detected_script = detected_script
        if reading_order_mode is not None:
            existing.reading_order_mode = reading_order_mode
        if engine_tier is not None:
            existing.engine_tier = engine_tier
        if page_width is not None:
            existing.page_width = page_width
        if page_height is not None:
            existing.page_height = page_height
        if ai_assisted_regions is not None:
            existing.ai_assisted_regions = ai_assisted_regions
        existing.last_accessed_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    # First write for this page: there is no incumbent to protect, and
    # refusing to cache would only make every later reader re-run OCR. It
    # is stored as-is, fingerprinted so the next submission can be judged
    # against it.
    entry = OcrCache(
        chapter_id=chapter_id,
        page_index=page_index,
        text_boxes=text_boxes,
        text_hash=submission_quality_gate.compute_text_hash(text_boxes),
        quality_tier=quality_tier,
        provider=provider,
        regions=regions,
        detected_language=detected_language,
        detected_script=detected_script,
        reading_order_mode=reading_order_mode,
        engine_tier=engine_tier,
        page_width=page_width,
        page_height=page_height,
        ai_assisted_regions=ai_assisted_regions,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _source_boxes_for(
    db: Session,
    chapter_id: int,
    page_index: int,
    ocr_cache_id: Optional[int],
) -> Optional[List[str]]:
    """The OCR text a translation for this page claims to render, so the
    gate can sanity-check length/script against it. Reads don't touch
    ``last_accessed_at`` -- this is a write-path lookup, not a cache hit."""

    row = None
    if ocr_cache_id is not None:
        row = db.get(OcrCache, ocr_cache_id)
    if row is None:
        row = (
            db.query(OcrCache)
            .filter(
                OcrCache.chapter_id == chapter_id, OcrCache.page_index == page_index
            )
            .one_or_none()
        )
    return list(row.text_boxes or []) if row is not None else None


def get_translation_cache(
    db: Session, chapter_id: int, page_index: int, target_lang: str
) -> Optional[TranslationCache]:
    entry = (
        db.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter_id,
            TranslationCache.page_index == page_index,
            TranslationCache.target_lang == target_lang,
        )
        .one_or_none()
    )
    if entry is not None:
        entry.last_accessed_at = datetime.utcnow()
        db.commit()
    return entry


def put_translation_cache(
    db: Session,
    chapter_id: int,
    page_index: int,
    target_lang: str,
    translated_boxes: List[str],
    *,
    quality_tier: str = DEFAULT_QUALITY_TIER,
    provider: Optional[str] = None,
    ocr_cache_id: Optional[int] = None,
    regions: Optional[List[Dict[str, Any]]] = None,
    ai_assisted_regions: Optional[List[int]] = None,
    contributed_by_sharing: bool = False,
    contributed_by_user_id: Optional[int] = None,
    source_boxes: Optional[List[str]] = None,
    quality_provider_config: Optional[Dict[str, Any]] = None,
    quality_scorer: Optional[Callable[..., Optional[float]]] = None,
    http_post: Callable[..., Any] = requests.post,
) -> TranslationCache:
    """Store translated output, upgrading in place only when it is better.

    Same two-stage rule as :func:`put_ocr_cache`: tier is a pre-filter,
    ``submission_quality_gate`` is the write authority at equal tier. A
    rejected submission leaves the stored entry -- including its
    ``contributed_by_user_id`` -- untouched, which is what keeps
    ``pill_service`` from rewarding a submission that never went live.

    ``source_boxes`` is the OCR text this translation claims to render; the
    gate uses it for the length/garbage rules. When omitted it is read from
    the linked OCR cache entry.
    """

    existing = (
        db.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter_id,
            TranslationCache.page_index == page_index,
            TranslationCache.target_lang == target_lang,
        )
        .one_or_none()
    )
    if existing is not None:
        if _tier_rank(quality_tier) < _tier_rank(existing.quality_tier):
            return existing
        if source_boxes is None:
            source_boxes = _source_boxes_for(
                db, chapter_id, page_index, ocr_cache_id or existing.ocr_cache_id
            )
        decision = submission_quality_gate.evaluate(
            new_boxes=translated_boxes,
            existing_boxes=existing.translated_boxes,
            existing_hash=existing.text_hash,
            existing_score=existing.quality_score,
            source_boxes=source_boxes,
            expected_language=target_lang,
            skip_scoring=_tier_rank(quality_tier) > _tier_rank(existing.quality_tier),
            # A shared user contribution is exactly the submission that can
            # earn a Pill, so it is the one that has to prove itself.
            trusted=not contributed_by_sharing,
            provider_config=quality_provider_config,
            scorer=quality_scorer,
            http_post=http_post,
        )
        if not decision.accepted:
            _record_rejection(db, existing, decision)
            return existing

        existing.translated_boxes = translated_boxes
        existing.text_hash = decision.text_hash
        existing.quality_score = decision.new_score
        existing.quality_tier = quality_tier
        existing.provider = provider
        existing.ocr_cache_id = ocr_cache_id
        if regions is not None:
            existing.regions = regions
        if ai_assisted_regions is not None:
            existing.ai_assisted_regions = ai_assisted_regions
        existing.contributed_by_sharing = contributed_by_sharing
        existing.contributed_by_user_id = (
            contributed_by_user_id if contributed_by_sharing else None
        )
        existing.last_accessed_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    entry = TranslationCache(
        chapter_id=chapter_id,
        page_index=page_index,
        target_lang=target_lang,
        translated_boxes=translated_boxes,
        text_hash=submission_quality_gate.compute_text_hash(translated_boxes),
        quality_tier=quality_tier,
        provider=provider,
        ocr_cache_id=ocr_cache_id,
        regions=regions,
        ai_assisted_regions=ai_assisted_regions,
        contributed_by_sharing=contributed_by_sharing,
        contributed_by_user_id=(
            contributed_by_user_id if contributed_by_sharing else None
        ),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def evict_stale(db: Session, *, older_than_days: int = 90) -> int:
    """LRU eviction: remove entries not accessed within ``older_than_days``.

    Deletes from translation_cache first since it may reference ocr_cache
    rows via a nullable FK, then ocr_cache, avoiding an FK violation.
    Returns the total number of rows removed.
    """

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    removed = (
        db.query(TranslationCache)
        .filter(TranslationCache.last_accessed_at < cutoff)
        .delete(synchronize_session=False)
    )
    removed += (
        db.query(OcrCache)
        .filter(OcrCache.last_accessed_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    # Bulk deletes bypass the ORM, so identity-mapped objects loaded earlier
    # in this session would otherwise still look "alive" to callers.
    db.expire_all()
    return removed


__all__ = [
    "get_ocr_cache",
    "put_ocr_cache",
    "get_translation_cache",
    "put_translation_cache",
    "evict_stale",
]
