"""CRUD for per-user processing preferences (Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2).

Runtime usage-counting/enforcement lives in ``usage_limit_service``; this
module only owns the settings row itself -- getting it (creating lazily on
first access), and applying validated partial updates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..models.processing_settings import (
    DEFAULT_AI_CONFIDENCE_THRESHOLD,
    MAX_OVERLAY_SCALE,
    MIN_OVERLAY_SCALE,
    OVERLAY_STYLES,
    USAGE_LIMIT_UNITS,
    USAGE_LIMIT_WINDOWS,
    UserProcessingSettings,
)
from .overlay_fonts import is_known_font


class ProcessingSettingsError(ValueError):
    """Raised when a settings update payload fails validation."""


def get_or_create(db: Session, user_id: int) -> UserProcessingSettings:
    record = db.get(UserProcessingSettings, user_id)
    if record is not None:
        return record
    record = UserProcessingSettings(user_id=user_id)
    db.add(record)
    db.flush()
    return record


def _validate_threshold(value: Any) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        raise ProcessingSettingsError("ai_confidence_threshold must be a number")
    if not (0.0 <= threshold <= 1.0):
        raise ProcessingSettingsError("ai_confidence_threshold must be between 0 and 1")
    return threshold


def _validate_scale(value: Any) -> int:
    try:
        scale = int(value)
    except (TypeError, ValueError):
        raise ProcessingSettingsError("overlay_font_size must be an integer")
    if not (MIN_OVERLAY_SCALE <= scale <= MAX_OVERLAY_SCALE):
        raise ProcessingSettingsError(
            f"overlay_font_size must be between {MIN_OVERLAY_SCALE} and {MAX_OVERLAY_SCALE}"
        )
    return scale


def update(
    db: Session, user_id: int, updates: Dict[str, Any]
) -> UserProcessingSettings:
    record = get_or_create(db, user_id)

    if "usage_limit_unit" in updates and updates["usage_limit_unit"] is not None:
        unit = str(updates["usage_limit_unit"]).strip().lower()
        if unit not in USAGE_LIMIT_UNITS:
            raise ProcessingSettingsError(
                f"usage_limit_unit must be one of {USAGE_LIMIT_UNITS}"
            )
        # 2E.1A: switching units does not retroactively convert the current
        # period's count -- it starts a fresh period under the new unit.
        if unit != record.usage_limit_unit:
            record.usage_current = 0
            record.ai_usage_current = 0
            record.usage_period_start = datetime.utcnow()
        record.usage_limit_unit = unit

    if "usage_limit_window" in updates and updates["usage_limit_window"] is not None:
        window = str(updates["usage_limit_window"]).strip().lower()
        if window not in USAGE_LIMIT_WINDOWS:
            raise ProcessingSettingsError(
                f"usage_limit_window must be one of {USAGE_LIMIT_WINDOWS}"
            )
        record.usage_limit_window = window

    if "usage_limit_value" in updates:
        raw = updates["usage_limit_value"]
        if raw is None:
            record.usage_limit_value = None
        else:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ProcessingSettingsError("usage_limit_value must be an integer")
            if value <= 0:
                raise ProcessingSettingsError("usage_limit_value must be positive")
            record.usage_limit_value = value

    if "ai_assist_enabled" in updates and updates["ai_assist_enabled"] is not None:
        record.ai_assist_enabled = bool(updates["ai_assist_enabled"])

    if (
        "ai_confidence_threshold" in updates
        and updates["ai_confidence_threshold"] is not None
    ):
        record.ai_confidence_threshold = _validate_threshold(
            updates["ai_confidence_threshold"]
        )

    if "share_translations" in updates and updates["share_translations"] is not None:
        record.share_translations = bool(updates["share_translations"])

    if "overlay_style" in updates and updates["overlay_style"] is not None:
        style = str(updates["overlay_style"]).strip().lower()
        if style not in OVERLAY_STYLES:
            raise ProcessingSettingsError(
                f"overlay_style must be one of {OVERLAY_STYLES}"
            )
        record.overlay_style = style

    if "overlay_font" in updates and updates["overlay_font"] is not None:
        font = str(updates["overlay_font"]).strip()
        if not is_known_font(font, db):
            raise ProcessingSettingsError("overlay_font is not in the curated set")
        record.overlay_font = font

    if "overlay_font_size" in updates and updates["overlay_font_size"] is not None:
        record.overlay_font_size = _validate_scale(updates["overlay_font_size"])

    if (
        "translate_sound_effects" in updates
        and updates["translate_sound_effects"] is not None
    ):
        record.translate_sound_effects = bool(updates["translate_sound_effects"])

    if (
        "auto_translate_comments" in updates
        and updates["auto_translate_comments"] is not None
    ):
        record.auto_translate_comments = bool(updates["auto_translate_comments"])

    db.commit()
    db.refresh(record)
    return record


def to_dict(record: UserProcessingSettings) -> Dict[str, Any]:
    return {
        "usage_limit_unit": record.usage_limit_unit,
        "usage_limit_window": record.usage_limit_window,
        "usage_limit_value": record.usage_limit_value,
        "usage_current": record.usage_current,
        "ai_usage_current": record.ai_usage_current,
        "usage_period_start": (
            record.usage_period_start.isoformat() if record.usage_period_start else None
        ),
        "ai_assist_enabled": bool(record.ai_assist_enabled),
        "ai_confidence_threshold": (
            record.ai_confidence_threshold
            if record.ai_confidence_threshold is not None
            else DEFAULT_AI_CONFIDENCE_THRESHOLD
        ),
        "share_translations": bool(record.share_translations),
        "overlay_style": record.overlay_style,
        "overlay_font": record.overlay_font,
        "overlay_font_size": record.overlay_font_size,
        "translate_sound_effects": bool(record.translate_sound_effects),
        "auto_translate_comments": bool(record.auto_translate_comments),
    }


__all__ = ["ProcessingSettingsError", "get_or_create", "update", "to_dict"]
