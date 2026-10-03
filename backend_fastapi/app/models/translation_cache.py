"""Shared OCR/translation cache (SRS 1H.14).

Two-layer split: ``OcrCache`` holds the detected text of a page once,
independent of target language; ``TranslationCache`` holds the translated
text of a page once per target language, referencing the OCR result it was
translated from. Both carry a ``quality_tier`` so a free-tier result can
later be superseded by a higher-quality (e.g. paid-provider) run, and a
``last_accessed_at`` timestamp for LRU eviction.

This module defined the data model and policy only for Part 1 (SRS 1H.14);
Part 2 wires the actual OCR/MT engines to read and populate these tables,
and adds the columns 2B.6's normalized OCR shape and 2C.1's whole-chapter
translation context need: per-region detail (``regions``), the detected
script/language and reading-order mode, page dimensions (for overlay
fit at read time, 2F.2), and which regions were AI-assisted (2A.3).
"""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    DateTime,
    JSON,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base

# Ordered worst-to-best; higher index = higher quality. Provider tier is a
# pre-filter only -- a strictly lower tier still loses outright -- but it is
# no longer what authorises a write. Because every untrusted engine lands in
# the same "free" bucket, an equal-tier write is decided by
# ``submission_quality_gate`` from the submitted text itself.
QUALITY_TIER_ORDER = {"free": 0, "paid": 1}
DEFAULT_QUALITY_TIER = "free"


class OcrCache(Base):
    """Detected text for one chapter page, independent of target language."""

    __tablename__ = "ocr_cache"
    __table_args__ = (
        Index("uq_ocr_cache_chapter_page", "chapter_id", "page_index", unique=True),
        Index("ix_ocr_cache_text_hash", "text_hash"),
    )

    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    page_index = Column(Integer, nullable=False)
    # Bare string array, one entry per detected text box/line, reading order.
    # Kept for backward compatibility; ``regions`` (below) is the 2B.6
    # normalized shape new writes populate and readers should prefer.
    text_boxes = Column(JSON, nullable=False)
    # 2B.6: [{index, text, coordinates, confidence, region_type, reading_order}]
    regions = Column(JSON, nullable=True)
    detected_language = Column(String(16), nullable=True)
    detected_script = Column(String(24), nullable=True)
    # 2B.4: rtl_vertical | ttb_column | ltr_ttb | rtl_ttb
    reading_order_mode = Column(String(24), nullable=True)
    # 2B.5 provider tier (1=local/basic .. 4=premium), drives quality tiering.
    engine_tier = Column(Integer, nullable=True)
    page_width = Column(Integer, nullable=True)
    page_height = Column(Integer, nullable=True)
    # 2A.3: region indices where AI corrected/supplemented OCR.
    ai_assisted_regions = Column(JSON, nullable=True)
    quality_tier = Column(
        String(16), nullable=False, default=DEFAULT_QUALITY_TIER, server_default="free"
    )
    # Content fingerprint of the stored text (submission_quality_gate.
    # compute_text_hash). An identical resubmission is recognised here
    # without reading or comparing the text itself.
    text_hash = Column(String(64), nullable=True)
    # 0-100 fidelity/coherence score for the stored text, populated only
    # when the quality gate actually had to score this entry. NULL simply
    # means "never scored", which is not the same as "scored badly".
    quality_score = Column(Float, nullable=True)
    provider = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    last_accessed_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    translations = relationship(
        "TranslationCache",
        back_populates="ocr_cache",
        cascade="all, delete-orphan",
    )


class TranslationCache(Base):
    """Translated text for one chapter page, per target language."""

    __tablename__ = "translation_cache"
    __table_args__ = (
        Index(
            "uq_translation_cache_chapter_page_lang",
            "chapter_id",
            "page_index",
            "target_lang",
            unique=True,
        ),
        Index("ix_translation_cache_text_hash", "text_hash"),
    )

    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    page_index = Column(Integer, nullable=False)
    target_lang = Column(String(16), nullable=False)
    ocr_cache_id = Column(Integer, ForeignKey("ocr_cache.id"), nullable=True)
    # Bare string array, same length/order as the source OcrCache.text_boxes.
    # Kept for backward compatibility; ``regions`` is the 2B.6-shaped,
    # translated-in-place region list new writes populate.
    translated_boxes = Column(JSON, nullable=False)
    # Same shape as OcrCache.regions, but ``text`` holds the translation.
    regions = Column(JSON, nullable=True)
    # 2A.3: region indices AI assisted for this translation.
    ai_assisted_regions = Column(JSON, nullable=True)
    # 2C.4.4 Mechanism B: whether this specific entry came from a user who
    # opted in to sharing -- distinct from Mechanism A (2C.4.3), which only
    # controls whether OTHER READERS are served from the cache by default.
    contributed_by_sharing = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 3C.3: which user contributed the entry currently stored here (only set
    # when contributed_by_sharing is True). Whoever's write is live here is
    # the "accepted version" a Pill mints for (1H.14.8 quality tiering) --
    # superseded by a later, better contribution simply overwrites this.
    contributed_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    quality_tier = Column(
        String(16), nullable=False, default=DEFAULT_QUALITY_TIER, server_default="free"
    )
    # See OcrCache above: content fingerprint + last known quality score for
    # whatever text is currently live here. Together they are what lets an
    # equal-tier resubmission be judged on content instead of on which
    # provider name it claims.
    text_hash = Column(String(64), nullable=True)
    quality_score = Column(Float, nullable=True)
    provider = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    last_accessed_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    ocr_cache = relationship("OcrCache", back_populates="translations")
