"""Chapter/page processing orchestration (SRS 2F.1).

The pipeline that ties together cache short-circuiting (2F.1's modified
Step 0/0b diagram), provider priority (2A), the normalized OCR shape
(2B.6), whole-chapter translation context (2C.1), the cache administration
mechanisms (2C.4), and usage limits (2E) into the one path a reader's page
view actually calls. In steady state, most reads execute Step 0 (cache
hit) and nothing else -- exactly what 2F.1 asks for.

All external effects (fetching the image, running OCR, calling the
translation/AI providers) are passed in as callables so this stays fully
testable without a real image, tesseract, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Chapter
from ..models.processing_settings import UserProcessingSettings
from . import (
    ai_assist,
    ai_vision_assist,
    cache_admin_service,
    chapter_translation_service,
    glossary_service,
    translation_cache_service,
    usage_limit_service,
)
from .processing_plan import ProcessingPlan

PAID_TIER_THRESHOLD = 3


@dataclass
class PageProcessingResult:
    chapter_id: int
    page_index: int
    target_lang: str
    regions: List[Dict[str, Any]]
    cached: bool
    ocr_cached: bool
    detected_language: Optional[str] = None
    detected_script: Optional[str] = None
    reading_order_mode: Optional[str] = None
    engine_tier: Optional[int] = None
    ai_assisted_regions: List[int] = field(default_factory=list)
    provider: Optional[str] = None
    used_fallback: bool = False
    notice: Optional[str] = None
    # 2C.1 Stage B: whether the coherence pass actually ran for this page.
    # False means the reader is looking at Stage A's literal drafts, which
    # is what happens when no chat-completion-capable provider is available.
    coherence_applied: bool = False
    coherence_reason: Optional[str] = None


def _quality_tier_for(engine_tier: Optional[int]) -> str:
    return "paid" if (engine_tier or 0) >= PAID_TIER_THRESHOLD else "free"


def _regions_from_translated_boxes(boxes: List[str]) -> List[Dict[str, Any]]:
    """Best-effort shape for a row that predates the 2B.6 ``regions``
    column (Part 1 wrote only ``text_boxes``/``translated_boxes``)."""

    return [
        {
            "index": i,
            "text": text,
            "coordinates": None,
            "confidence": None,
            "region_type": None,
            "reading_order": i,
        }
        for i, text in enumerate(boxes or [])
    ]


def _sibling_context_lines(
    db: Session, chapter_id: int, exclude_page_index: int
) -> List[str]:
    """Text already known for OTHER pages of this chapter (from OCR cache),
    used purely as translation context (2C.1) -- never re-translated."""

    rows = (
        db.query(translation_cache_service.OcrCache)
        .filter(
            translation_cache_service.OcrCache.chapter_id == chapter_id,
            translation_cache_service.OcrCache.page_index != exclude_page_index,
        )
        .order_by(translation_cache_service.OcrCache.page_index)
        .all()
    )
    lines: List[str] = []
    for row in rows:
        for region in row.regions or []:
            text = (region or {}).get("text")
            if text and text.strip():
                lines.append(text.strip())
    return lines[-40:]  # bound prompt size


def _previous_page_last_lines(
    db: Session, chapter_id: int, page_index: int, target_lang: str, limit: int = 6
) -> List[str]:
    """How the immediately preceding page ended (2C.1 Stage B context).

    Prefers that page's already-translated text so the coherence pass can
    continue the same voice in the target language, and falls back to its
    source text when the page hasn't been translated yet.

    Both rows are read straight off the query rather than through
    ``get_translation_cache``/``get_ocr_cache``: those bump
    ``last_accessed_at``, and assembling a prompt is not a cache hit -- it
    must not reorder LRU eviction.
    """

    if page_index <= 0:
        return []

    previous = page_index - 1
    cached = (
        db.query(translation_cache_service.TranslationCache)
        .filter(
            translation_cache_service.TranslationCache.chapter_id == chapter_id,
            translation_cache_service.TranslationCache.page_index == previous,
            translation_cache_service.TranslationCache.target_lang == target_lang,
        )
        .one_or_none()
    )
    regions = (cached.regions if cached is not None else None) or []
    if not regions:
        ocr_row = (
            db.query(translation_cache_service.OcrCache)
            .filter(
                translation_cache_service.OcrCache.chapter_id == chapter_id,
                translation_cache_service.OcrCache.page_index == previous,
            )
            .one_or_none()
        )
        regions = (ocr_row.regions if ocr_row is not None else None) or []

    lines = [
        str((region or {}).get("text") or "").strip()
        for region in regions
        if str((region or {}).get("text") or "").strip()
    ]
    return lines[-limit:]


def _chapter_summary(
    series_title: Optional[str],
    genres: Optional[List[str]],
    context_lines: List[str],
) -> Optional[str]:
    """A compact stand-in for a chapter synopsis.

    There is no authored synopsis anywhere in the data model, so this is
    assembled from what is actually known: what the series is, and a bounded
    digest of dialogue already recorded elsewhere in this chapter. It is
    background for the coherence pass, never something to translate.
    """

    parts: List[str] = []
    if series_title:
        parts.append(f"Series: {series_title}.")
    if genres:
        parts.append(f"Genre: {', '.join(genres)}.")
    digest = " / ".join(context_lines[-20:])
    if digest:
        parts.append(f"Dialogue recorded elsewhere in this chapter: {digest}")
    return " ".join(parts) or None


def process_page(
    db: Session,
    *,
    chapter: Chapter,
    page_index: int,
    target_lang: str,
    user_id: int,
    plan: ProcessingPlan,
    processing_settings: UserProcessingSettings,
    fetch_image_bytes: Callable[[str], bytes],
    ocr_runner: Callable[[bytes, Optional[str]], Dict[str, Any]],
    translation_service: Any,
    translation_provider_config: Optional[Dict[str, Any]],
    ai_provider_config: Optional[Dict[str, Any]],
    load_image_for_vision: Callable[[bytes], Any] = lambda _b: None,
    reader_requested_cached: bool = False,
    source_lang_hint: Optional[str] = None,
    series_title: Optional[str] = None,
    genres: Optional[List[str]] = None,
    client_draft_translations: Optional[List[Any]] = None,
) -> PageProcessingResult:
    """Process one page.

    ``client_draft_translations`` is Pipeline 1's client-side (LibreTranslate)
    output for this page, positionally aligned with the page's regions. When
    supplied it is reused as Stage A's literal draft instead of re-translating
    server-side; Stage B still rewrites it, so nothing is lost by reusing it.
    """

    pages = chapter.pages or []
    if page_index < 0 or page_index >= len(pages):
        raise ValueError("page_index out of range")

    cache_priority = cache_admin_service.get_cache_priority(db)

    # Step 0: translation-cache short circuit -- most reads stop here.
    if cache_admin_service.should_check_cache(
        cache_priority, reader_requested_cached=reader_requested_cached
    ):
        cached = translation_cache_service.get_translation_cache(
            db, chapter.id, page_index, target_lang
        )
        if cached is not None:
            regions = cached.regions or _regions_from_translated_boxes(
                cached.translated_boxes
            )
            return PageProcessingResult(
                chapter_id=chapter.id,
                page_index=page_index,
                target_lang=target_lang,
                regions=regions,
                cached=True,
                ocr_cached=True,
                provider=cached.provider,
                ai_assisted_regions=cached.ai_assisted_regions or [],
            )

    # Step 0b: OCR-cache short circuit.
    ocr_row = translation_cache_service.get_ocr_cache(db, chapter.id, page_index)
    image_for_vision = None
    if ocr_row is not None and ocr_row.regions:
        normalized: Dict[str, Any] = {
            "regions": ocr_row.regions,
            "detected_language": ocr_row.detected_language,
            "detected_script": ocr_row.detected_script,
            "reading_order_mode": ocr_row.reading_order_mode,
            "engine_tier": ocr_row.engine_tier,
        }
        ocr_cached = True
        ocr_ai_assisted = ocr_row.ai_assisted_regions or []
    else:
        # Fresh OCR: one page of quota, regardless of how many regions it
        # contains (2E.1A). Cache hits above never reach this line.
        usage_limit_service.check_and_consume(db, user_id, "translation", 1)

        image_bytes = fetch_image_bytes(pages[page_index])
        normalized = ocr_runner(image_bytes, source_lang_hint)
        ocr_cached = False
        image_for_vision = load_image_for_vision(image_bytes)

        ai_plan = ai_assist.plan_ai_assist(
            normalized.get("regions", []),
            ai_assist_enabled=bool(processing_settings.ai_assist_enabled),
            confidence_threshold=float(processing_settings.ai_confidence_threshold),
            ai_available=bool(ai_provider_config),
        )
        ocr_ai_assisted = []
        if (
            ai_plan.mode != "none"
            and ai_provider_config
            and image_for_vision is not None
        ):
            region_by_index = {r["index"]: r for r in normalized.get("regions", [])}
            if ai_plan.mode == "whole_page":
                # F-15: whole_page mode dispatches one combined call here
                # instead of looping assist_region() per index.
                flagged = [
                    region_by_index[idx]
                    for idx in ai_plan.region_indices
                    if region_by_index.get(idx) is not None
                    and region_by_index[idx].get("coordinates")
                ]
                corrections = ai_vision_assist.assist_page(
                    image_for_vision,
                    flagged,
                    provider_config=ai_provider_config,
                    language_hint=normalized.get("detected_language"),
                )
                for idx in ai_plan.region_indices:
                    region = region_by_index.get(idx)
                    corrected = corrections.get(idx)
                    if region is not None and corrected:
                        region["text"] = corrected
                        ocr_ai_assisted.append(idx)
            else:
                for idx in ai_plan.region_indices:
                    region = region_by_index.get(idx)
                    if region is None or not region.get("coordinates"):
                        continue
                    corrected = ai_vision_assist.assist_region(
                        image_for_vision,
                        region["coordinates"],
                        provider_config=ai_provider_config,
                        language_hint=normalized.get("detected_language"),
                    )
                    if corrected:
                        region["text"] = corrected
                        ocr_ai_assisted.append(idx)
            if ocr_ai_assisted:
                usage_limit_service.check_and_consume(db, user_id, "ai", 1)

        ocr_provider = (
            (translation_provider_config or {}).get("provider")
            if translation_provider_config
            else None
        )
        engine_tier = normalized.get("engine_tier")
        translation_cache_service.put_ocr_cache(
            db,
            chapter.id,
            page_index,
            [r.get("text", "") for r in normalized.get("regions", [])],
            quality_tier=_quality_tier_for(engine_tier),
            provider=ocr_provider,
            regions=normalized.get("regions"),
            detected_language=normalized.get("detected_language"),
            detected_script=normalized.get("detected_script"),
            reading_order_mode=normalized.get("reading_order_mode"),
            engine_tier=engine_tier,
            ai_assisted_regions=ocr_ai_assisted or None,
            trusted=plan.ocr_source == "platform_default",
            quality_provider_config=ai_provider_config,
        )

    regions = normalized.get("regions", [])
    texts = [r.get("text", "") for r in regions]

    glossary = {}
    if chapter.manga_id:
        glossary = glossary_service.get_glossary(db, chapter.manga_id, target_lang)
    context_lines = _sibling_context_lines(db, chapter.id, page_index)

    # 2C.1: Stage A drafts literally, Stage B applies the context. The AI
    # provider is offered to Stage B because it is the chat-completion-capable
    # one in every plan; if it isn't configured, coherence_pass falls back to
    # the translation provider and then the system default, and only skips the
    # pass when none of them can hold a conversation.
    coherence_outcome: Dict[str, Any] = {}
    translated_texts = chapter_translation_service.translate_chapter_texts(
        texts,
        translation_service=translation_service,
        provider_config=translation_provider_config,
        source_lang=normalized.get("detected_language") or source_lang_hint or "auto",
        target_lang=target_lang,
        series_title=series_title,
        genres=genres,
        glossary=glossary,
        context_lines=context_lines,
        regions=regions,
        draft_translations=client_draft_translations,
        coherence_provider_config=ai_provider_config,
        previous_page_last_lines=_previous_page_last_lines(
            db, chapter.id, page_index, target_lang
        ),
        chapter_summary=_chapter_summary(series_title, genres, context_lines),
        coherence_outcome=coherence_outcome,
        context_aware=bool(getattr(processing_settings, "context_translation", True)),
    )

    translated_regions: List[Dict[str, Any]] = []
    for region, translated in zip(regions, translated_texts):
        merged = dict(region)
        merged["text"] = translated
        merged["source_text"] = region.get("text")
        translated_regions.append(merged)

    translation_provider = (
        (translation_provider_config or {}).get("provider")
        if translation_provider_config
        else None
    )
    should_share = (
        bool(processing_settings.share_translations)
        and plan.translation_source == "user"
    )
    should_write_shared = (
        plan.translation_source == "platform_default" or should_share
    ) and coherence_outcome.get("reason") != "disabled_by_user"
    # ^ A reader who turned the context pass off gets a literal draft; that
    # must not become the shared copy other readers are served.

    # What follows is written from ``translated_regions``, i.e. Stage B's
    # output whenever the coherence pass ran -- the literal Stage A draft is
    # never what enters the shared cache while a refined version exists.
    # put_translation_cache runs the quality gate on it before writing.
    if should_write_shared:
        written = translation_cache_service.put_translation_cache(
            db,
            chapter.id,
            page_index,
            target_lang,
            [r.get("text", "") for r in translated_regions],
            quality_tier=_quality_tier_for(normalized.get("engine_tier")),
            provider=translation_provider,
            ocr_cache_id=ocr_row.id if ocr_row is not None else None,
            regions=translated_regions,
            ai_assisted_regions=ocr_ai_assisted or None,
            contributed_by_sharing=should_share,
            contributed_by_user_id=user_id if should_share else None,
            source_boxes=texts,
            quality_provider_config=ai_provider_config,
        )
        # 3C.3: a Pill is minted only when this user's shared contribution is
        # the version that actually won the quality gate and is now live --
        # not merely attempted. ``written.contributed_by_user_id`` reflects
        # whichever write is currently live for this page, so a submission
        # the gate rejected returns the incumbent's owner here and mints
        # nothing. Ordering matters: the write is attempted first, and only
        # its outcome decides whether a Pill is minted.
        if should_share and written.contributed_by_user_id == user_id:
            from . import pill_service

            pill_service.mint_if_new(
                db, user_id=user_id, chapter_id=chapter.id, target_lang=target_lang
            )

    return PageProcessingResult(
        chapter_id=chapter.id,
        page_index=page_index,
        target_lang=target_lang,
        regions=translated_regions,
        cached=False,
        ocr_cached=ocr_cached,
        detected_language=normalized.get("detected_language"),
        detected_script=normalized.get("detected_script"),
        reading_order_mode=normalized.get("reading_order_mode"),
        engine_tier=normalized.get("engine_tier"),
        ai_assisted_regions=ocr_ai_assisted,
        provider=translation_provider,
        coherence_applied=bool(coherence_outcome.get("applied")),
        coherence_reason=coherence_outcome.get("reason"),
    )


__all__ = ["PageProcessingResult", "process_page"]
