"""Per-user processing preferences (SRS Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2).

Kept off the core ``User`` table, mirroring the existing split for
``NotificationPreference`` -- a cohesive group of processing/reading
preferences that has nothing to do with identity or auth. One row per user,
created lazily on first access (see ``processing_settings_service``).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base

# 2E.1A: the user's choice of unit for their own usage ceiling.
USAGE_LIMIT_UNITS = ("pages", "words")
DEFAULT_USAGE_LIMIT_UNIT = "pages"

# 1E.1.3: month is the maximum window: there is no yearly limit.
USAGE_LIMIT_WINDOWS = ("day", "week", "month")
DEFAULT_USAGE_LIMIT_WINDOW = "week"

# 2F.2: supported overlay box styles.
OVERLAY_STYLES = (
    "white_box",
    "transparent_box",
    "colored_box",
    "speech_bubble",
    "custom",
)
DEFAULT_OVERLAY_STYLE = "white_box"

# 2F.2A: curated default; the full curated set lives in
# services.overlay_fonts (admin-extensible without a code change).
DEFAULT_OVERLAY_FONT = "standard_sans"

# Translated-text size: the reader's slider runs 1-100 in half steps and the
# overlay draws value * OVERLAY_PX_PER_STEP pixels (100 -> 70 px). The default
# 28.5 is the old 20 px baseline (2F.2B).
DEFAULT_OVERLAY_SCALE = 28.5
MIN_OVERLAY_SCALE = 1
MAX_OVERLAY_SCALE = 100
OVERLAY_SCALE_STEP = 0.5
OVERLAY_PX_PER_STEP = 0.7

# Language the overlay translates into unless the reader picks another.
DEFAULT_TARGET_LANGUAGE = "en"
TARGET_LANGUAGES = ("en", "es", "fr", "de", "pt", "it", "ru", "ar", "hi", "bn", "id", "vi", "th", "tr", "ja", "ko", "zh")

# D12: default confidence threshold that triggers AI assistance. Chosen as a
# moderate midpoint -- low enough to catch genuinely weak OCR, high enough
# that most successful recognitions never wake the AI path (2A.3's "AI must
# not unnecessarily consume resources"). Configurable per user.
DEFAULT_AI_CONFIDENCE_THRESHOLD = 0.6


class UserProcessingSettings(Base):
    __tablename__ = "user_processing_settings"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # ---- 2E.1 / 2E.1A: usage limits, page- or word-based, user's choice ----
    usage_limit_unit = Column(
        String(8),
        nullable=False,
        default=DEFAULT_USAGE_LIMIT_UNIT,
        server_default=DEFAULT_USAGE_LIMIT_UNIT,
    )
    usage_limit_window = Column(
        String(8),
        nullable=False,
        default=DEFAULT_USAGE_LIMIT_WINDOW,
        server_default=DEFAULT_USAGE_LIMIT_WINDOW,
    )
    # NULL = no limit configured; processing is unbounded (subject to
    # platform-wide ceilings, 2E.3).
    usage_limit_value = Column(Integer, nullable=True)
    # 2E.2: separate counters -- OCR+translation ("processing") vs AI --
    # both measured in usage_limit_unit, both reset on usage_limit_window.
    usage_current = Column(Integer, nullable=False, default=0, server_default="0")
    ai_usage_current = Column(Integer, nullable=False, default=0, server_default="0")
    usage_period_start = Column(DateTime, nullable=False, server_default=func.now())

    # ---- 2A.3 / D12: AI assistance ----
    ai_assist_enabled = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    ai_confidence_threshold = Column(
        Float,
        nullable=False,
        default=DEFAULT_AI_CONFIDENCE_THRESHOLD,
        server_default=str(DEFAULT_AI_CONFIDENCE_THRESHOLD),
    )

    # ---- 2C.4.4: voluntary sharing (Mechanism B) -- off by default, an
    # opt-in never overridden by the admin's Mechanism A setting.
    share_translations = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ---- 2F.2 / 2F.2A / 2F.2B: overlay rendering preferences ----
    overlay_style = Column(
        String(20),
        nullable=False,
        default=DEFAULT_OVERLAY_STYLE,
        server_default=DEFAULT_OVERLAY_STYLE,
    )
    overlay_font = Column(
        String(60),
        nullable=False,
        default=DEFAULT_OVERLAY_FONT,
        server_default=DEFAULT_OVERLAY_FONT,
    )
    # The account-level default scale (1E.1.2 overlay_font_size); a chapter
    # session may override this locally and optionally save it back here
    # (2F.2B).
    overlay_font_size = Column(
        Float,
        nullable=False,
        default=DEFAULT_OVERLAY_SCALE,
        server_default=str(DEFAULT_OVERLAY_SCALE),
    )

    # ---- 2F.3 / D13: sound-effect translation. Resolved on by default,
    # matching the spec's "user CAN disable" phrasing (opt-out, not opt-in).
    translate_sound_effects = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ---- 3A.5: automatic comment translation. On by default (the whole
    # point is no button click); the reader can opt out.
    auto_translate_comments = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ---- Reader overlay, set once in Settings (no per-chapter toggle) ----
    # Translate pages automatically when a chapter opens.
    overlay_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    target_language = Column(
        String(8), nullable=False, default=DEFAULT_TARGET_LANGUAGE, server_default=DEFAULT_TARGET_LANGUAGE
    )
    # "#rrggbb"; NULL = automatic (sampled from the bubble / readable contrast).
    overlay_text_color = Column(String(7), nullable=True)
    overlay_box_color = Column(String(7), nullable=True)
    overlay_box_opacity = Column(Integer, nullable=False, default=100, server_default="100")
    # Outline drawn around the translated letters; None = automatic.
    overlay_outline_color = Column(String(7), nullable=True)
    # Draw the translation inside the bubble's own shape (ellipse, rectangle,
    # freeform) when one was recognised; off = always the plain box.
    overlay_match_bubble = Column(Boolean, nullable=False, default=True, server_default="true")
    # Context-aware AI pass over the whole page (reads the conversation,
    # keeps names/pronouns consistent). Off = literal line-by-line only.
    context_translation = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", lazy="selectin", back_populates="processing_settings")


__all__ = [
    "UserProcessingSettings",
    "USAGE_LIMIT_UNITS",
    "DEFAULT_USAGE_LIMIT_UNIT",
    "USAGE_LIMIT_WINDOWS",
    "DEFAULT_USAGE_LIMIT_WINDOW",
    "OVERLAY_STYLES",
    "DEFAULT_OVERLAY_STYLE",
    "DEFAULT_OVERLAY_FONT",
    "DEFAULT_OVERLAY_SCALE",
    "MIN_OVERLAY_SCALE",
    "MAX_OVERLAY_SCALE",
    "OVERLAY_SCALE_STEP",
    "OVERLAY_PX_PER_STEP",
    "DEFAULT_AI_CONFIDENCE_THRESHOLD",
]
