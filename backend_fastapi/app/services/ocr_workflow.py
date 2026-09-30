"""OCR helper routines reused across routers and services."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from .translation_service import TranslationService

logger = structlog.get_logger("backend_fastapi.ocr.workflow")

# M2 / Blind Spot #9: bound how many overlay text boxes translate at once so we
# fan out concurrently (instead of strictly one-by-one) while still respecting
# provider rate limits. translate_overlay_items runs inside a worker thread
# (run_in_heavy_threadpool), so a bounded ThreadPoolExecutor is the natural
# concurrency primitive here — equivalent to asyncio.gather + a semaphore.
_TRANSLATION_MAX_CONCURRENCY = max(
    1, int(os.getenv("TRANSLATION_MAX_CONCURRENCY", "5"))
)

__all__ = [
    "normalize_overlay_boxes",
    "translate_overlay_items",
    "combine_translated_text",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_overlay_boxes(
    items: Iterable[Dict[str, Any]], page: Dict[str, Any]
) -> List[Dict[str, Any]]:
    width = _safe_float(page.get("width"))
    height = _safe_float(page.get("height"))
    if width <= 0 or height <= 0:
        return []

    boxes: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        left = _safe_float(item.get("left"))
        top = _safe_float(item.get("top"))
        box_width = _safe_float(item.get("width"))
        box_height = _safe_float(item.get("height"))
        translated = ""
        if isinstance(item.get("translated"), str):
            translated = item["translated"].strip()
        elif isinstance(item.get("translation"), str):
            translated = item["translation"].strip()

        normalized = {
            "x": max(0.0, min(1.0, left / width)),
            "y": max(0.0, min(1.0, top / height)),
            "w": max(0.0, min(1.0, box_width / width)),
            "h": max(0.0, min(1.0, box_height / height)),
            "text": text,
        }
        if translated:
            normalized["translated"] = translated
        boxes.append(normalized)

    return boxes


def _provider_name(provider_config: Optional[Dict[str, Any]]) -> Optional[str]:
    if not provider_config or not isinstance(provider_config, dict):
        return None
    raw = provider_config.get("provider") or provider_config.get("provider_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _translate_items_concurrently(
    items: List[Dict[str, Any]],
    *,
    translation_service: TranslationService,
    provider_config: Optional[Dict[str, Any]],
    target_lang: str,
    source_lang: Optional[str],
    errors: List[str],
) -> List[str]:
    """Translate each item's text concurrently, preserving input order.

    Empty/blank boxes are skipped (kept as ""), non-empty boxes are translated
    with a bounded worker pool. On a per-box failure the original text is kept
    and a ``translation_failed`` error is recorded.
    """

    translations: List[Optional[str]] = [None] * len(items)
    pending: List[int] = []

    for idx, item in enumerate(items):
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            translations[idx] = ""
        else:
            pending.append(idx)

    if not pending:
        return ["" if value is None else value for value in translations]

    def _one(idx: int) -> tuple[int, str, bool]:
        text = items[idx]["text"]
        try:
            translated = translation_service.translate(
                text,
                source_lang=source_lang or "auto",
                target_lang=target_lang,
                provider_config=provider_config,
            )
            return idx, translated, True
        except Exception as exc:  # pragma: no cover - defensive path
            logger.exception("Translation failure for overlay: %s", exc)
            return idx, text, False

    workers = min(_TRANSLATION_MAX_CONCURRENCY, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for idx, value, ok in executor.map(_one, pending):
            translations[idx] = value
            if not ok:
                errors.append("translation_failed")

    return ["" if value is None else value for value in translations]


def translate_overlay_items(
    items: List[Dict[str, Any]],
    page: Dict[str, Any],
    metadata: Dict[str, Any],
    *,
    translation_service: TranslationService | None,
    provider_config: Optional[Dict[str, Any]],
    target_lang: str,
    source_lang: Optional[str] = None,
    used_ai_fallback: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    errors: List[str] = []
    translations: List[str] = []

    if translation_service is None:
        errors.append("translation_unavailable")
        translations = ["" for _ in items]
    else:
        translations = _translate_items_concurrently(
            items,
            translation_service=translation_service,
            provider_config=provider_config,
            target_lang=target_lang,
            source_lang=source_lang,
            errors=errors,
        )

    for item, translated_text in zip(items, translations):
        if (
            isinstance(item, dict)
            and isinstance(translated_text, str)
            and translated_text
        ):
            item["translated"] = translated_text

    boxes = normalize_overlay_boxes(items, page)

    provider_name = _provider_name(provider_config)
    translation_meta = {
        "target": target_lang,
        "source": source_lang or "auto",
        "used_ai_fallback": used_ai_fallback,
        "provider": provider_name,
        "errors": errors,
    }

    metadata = metadata or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["translation"] = translation_meta

    return boxes, metadata, errors


def combine_translated_text(items: Iterable[Dict[str, Any]]) -> str:
    segments: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate = item.get("translated") or item.get("text")
        if isinstance(candidate, str) and candidate.strip():
            segments.append(candidate.strip())
    return " ".join(segments).strip()
