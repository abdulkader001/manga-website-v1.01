"""Automatic comment translation (SRS 3A.5).

Reuses the same cache-then-translate architecture as manga pages (1H.14):
a comment's translation into a given target language is computed once and
shared with every reader reading in that language. The original text is
never overwritten -- "Show original" always has something real to show.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.community import CommentTranslation
from ..models.user import Comment
from . import script_registry


def detect_source_language(text: str, *, hint: Optional[str] = None) -> Optional[str]:
    """Same script/character-range heuristic used for OCR'd manga text
    (``script_registry.detect_language``) -- applies just as well to plain
    comment text."""

    language, _script = script_registry.detect_language(text or "", hint=hint)
    return language


def get_cached(
    db: Session, comment_id: int, target_lang: str
) -> Optional[CommentTranslation]:
    entry = (
        db.query(CommentTranslation)
        .filter(
            CommentTranslation.comment_id == comment_id,
            CommentTranslation.target_lang == target_lang,
        )
        .one_or_none()
    )
    if entry is not None:
        entry.last_accessed_at = datetime.utcnow()
        db.commit()
    return entry


def translate_comment(
    db: Session,
    comment: Comment,
    target_lang: str,
    *,
    translation_service: Any,
) -> Optional[str]:
    """Return the translated body of ``comment`` in ``target_lang``.

    Returns ``None`` when the comment is already in the reader's language
    (3A.5: "never translated") or when no translation provider is
    configured -- the caller falls back to showing the original.
    """

    if not target_lang or not comment.content:
        return None
    if comment.source_language and comment.source_language == target_lang:
        return None

    cached = get_cached(db, comment.id, target_lang)
    if cached is not None:
        return cached.translated_content

    if translation_service is None:
        return None

    translated = translation_service.translate(
        comment.content, comment.source_language or "auto", target_lang
    )
    if not translated or translated.strip() == comment.content.strip():
        return None

    provider = None
    default_config = getattr(translation_service, "default_provider_config", None)
    if isinstance(default_config, dict):
        provider = default_config.get("provider")

    entry = CommentTranslation(
        comment_id=comment.id,
        target_lang=target_lang,
        translated_content=translated,
        provider=provider,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        # Another request translated the same comment/language concurrently.
        db.rollback()
        cached = get_cached(db, comment.id, target_lang)
        return cached.translated_content if cached else translated
    return translated


def invalidate(db: Session, comment_id: int) -> None:
    """Drop cached translations after the original text changes (edit)."""

    db.query(CommentTranslation).filter(
        CommentTranslation.comment_id == comment_id
    ).delete()
    db.commit()


__all__ = [
    "detect_source_language",
    "get_cached",
    "translate_comment",
    "invalidate",
]
