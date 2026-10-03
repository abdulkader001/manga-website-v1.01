from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    DECIMAL,
    BigInteger,
    Boolean,
    func,
    Enum,
    Index,
    text as sa_text,
)
from sqlalchemy.orm import relationship

from .base import Base
from ..utils.cdn import build_cdn_url



def format_count(value: int) -> str:
    """Compact reader-facing count: 950, 1.2k, 3.4M."""

    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def _display_title(raw, number) -> str | None:
    """"Chapter N" plus whatever the source title says beyond the number and
    date (series-level noise and translation are handled by
    services.chapter_title_service for the reader views)."""

    from ..services.chapter_title_service import clean_title, needs_translation

    label = f"Chapter {number}" if number is not None else None
    sub = clean_title(raw, number)
    if sub and not needs_translation(sub, "en"):
        return f"{label}: {sub}" if label else sub
    return label or raw


def chapter_number_value(raw) -> int | float | None:
    """DECIMAL chapter number as a JSON number (12 rather than "12.00")."""

    if raw is None:
        return None
    number = float(raw)
    return int(number) if number.is_integer() else number


def scrape_frequency_label(interval_hours: int | None) -> str | None:
    if not interval_hours:
        return None
    if interval_hours < 24:
        return "hourly"
    days = interval_hours / 24
    if days <= 3:
        return "daily"
    if days <= 10:
        return "weekly"
    if days <= 20:
        return "biweekly"
    return "monthly"

# ----------------
# Manga, Chapter, History, Bookmark
# ----------------
class Manga(Base):
    __tablename__ = "manga"
    __table_args__ = (
        Index("ix_manga_popularity", "popularity"),
        Index("ix_manga_updated_at", "updated_at"),
        Index("ix_manga_created_at", "created_at"),
        # H3: title search index. The DB-level index is created by migration
        # 20260413_add_gin_and_search_indexes; declaring it here keeps the ORM
        # metadata (and fresh create_all in tests) in sync with the DB.
        Index("ix_manga_title", "title"),
    )
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String(255), unique=True, nullable=True)
    cover_image = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    source_url = Column(String, unique=True, nullable=False)
    language = Column(String(5), nullable=True)

    type = Column(
        Enum("manga", "manhwa", "manhua", name="manga_type"),
        nullable=False,
        default="manga",
    )
    status = Column(
        Enum(
            "ongoing", "completed", "hiatus", "dropped", "cancelled", name="manga_status"
        ),
        nullable=False,
        default="ongoing",
    )
    last_chapter_at = Column(DateTime, nullable=True)

    genres = Column(JSON, nullable=True)
    last_scraped = Column(DateTime, nullable=True)

    # ----- Series record fields (SRS 1G.1.2) ----------------------------
    original_title = Column(String, nullable=True)
    alternative_titles = Column(JSON, nullable=True)
    authors = Column(JSON, nullable=True)
    artists = Column(JSON, nullable=True)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # queued | scraping | complete | failed
    ingestion_status = Column(
        String(16), nullable=False, default="complete", server_default="complete"
    )
    last_error = Column(Text, nullable=True)
    # ----- Scheduled new-chapter detection (SRS 1G.12A) ------------------
    next_check_at = Column(DateTime, nullable=True)
    # Per-series override (1G.12A.5); NULL means "use the website default".
    check_interval_hours = Column(Integer, nullable=True)

    # ----- Content rights (SRS 1J) --------------------------------------
    # ``may_host`` and ``may_translate`` are SEPARATE permissions: a
    # NoDerivatives licence permits hosting but forbids translation, so the two
    # flags move independently. A series whose ``may_translate`` is False cannot
    # be translated by any path or any role, including the Permanent
    # Administrator. Both default to True so existing rows keep working; the
    # website-level defaults on ``ApprovedSourceDomain`` are ANDed in when
    # rights are resolved.
    may_host = Column(
        Boolean, nullable=False, default=True, server_default=sa_text("true")
    )
    may_translate = Column(
        Boolean, nullable=False, default=True, server_default=sa_text("true")
    )
    attribution = Column(String(512), nullable=True)
    rights_note = Column(Text, nullable=True)
    # Takedown workflow: none | requested | taken_down
    takedown_status = Column(
        String(32), nullable=False, default="none", server_default="none"
    )
    takedown_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    popularity = Column(Integer, nullable=True)

    # ----- Reader-facing catalogue fields ---------------------------------
    # Metadata (title, description, genres, authors, cover) is sourced from
    # MangaUpdates when a link is supplied; chapters come from ``source_url``.
    mangaupdates_url = Column(String(512), nullable=True)
    is_hot = Column(Boolean, nullable=False, default=False, server_default=sa_text("false"))
    views = Column(BigInteger, nullable=False, default=0, server_default="0")
    # Pausing keeps the interval but stops scheduled new-chapter checks.
    auto_scrape_enabled = Column(
        Boolean, nullable=False, default=True, server_default=sa_text("true")
    )
    # How this source lays its chapters/pages out:
    # ``{"group_size": 5, "spread_mode": "auto", "reading_direction": "rtl"}``.
    # See services/chapter_grouping.py.
    scrape_layout = Column(JSON, nullable=True)

    chapters = relationship(
        "Chapter", lazy="select", back_populates="manga", cascade="all, delete-orphan"
    )
    scraping_jobs = relationship(
        "ScrapingJob",
        lazy="select",
        back_populates="manga",
        cascade="all, delete-orphan",
    )
    bookmarks = relationship(
        "Bookmark",
        lazy="select",
        back_populates="manga",
        cascade="all, delete-orphan",
    )
    read_history_entries = relationship(
        "ReadHistory",
        lazy="select",
        back_populates="manga",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "cover_image": self.cover_image,
            "cover_url": build_cdn_url(self.cover_image),
            "description": self.description,
            "source_url": self.source_url,
            "language": self.language,
            "type": self.type,
            "status": self.status,
            "last_chapter_at": (
                self.last_chapter_at.isoformat() if self.last_chapter_at else None
            ),
            "genres": self.genres or [],
            "original_title": self.original_title,
            "alternative_titles": self.alternative_titles or [],
            "authors": self.authors or [],
            "artists": self.artists or [],
            "added_by": self.added_by,
            "ingestion_status": self.ingestion_status or "complete",
            "last_error": self.last_error,
            "next_check_at": (
                self.next_check_at.isoformat() if self.next_check_at else None
            ),
            "check_interval_hours": self.check_interval_hours,
            "popularity": self.popularity,
            "last_scraped": (
                self.last_scraped.isoformat() if self.last_scraped else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "may_host": bool(self.may_host) if self.may_host is not None else True,
            "may_translate": (
                bool(self.may_translate) if self.may_translate is not None else True
            ),
            "attribution": self.attribution,
            "takedown_status": self.takedown_status or "none",
            **self._catalogue_fields(),
        }

    def _catalogue_fields(self) -> dict:
        """Presentation fields the reader UI renders on cards and detail pages.

        Aggregates that need other tables (ratings, chapter counts, period
        views) are filled in by ``catalogue_service.enrich``.
        """

        authors = [a for a in (self.authors or []) if isinstance(a, str) and a]
        artists = [a for a in (self.artists or []) if isinstance(a, str) and a]
        interval_hours = self.check_interval_hours
        if interval_hours and interval_hours % 24 == 0:
            interval_value, interval_unit = interval_hours // 24, "days"
        elif interval_hours:
            interval_value, interval_unit = interval_hours, "hours"
        else:
            interval_value, interval_unit = None, None
        views = int(self.views or 0)
        cover = build_cdn_url(self.cover_image)
        return {
            "author": ", ".join(authors) or None,
            "artist": ", ".join(artists) or None,
            "alt_titles": self.alternative_titles or [],
            "mangaupdates_url": self.mangaupdates_url,
            "is_hot": bool(self.is_hot),
            "views": views,
            "views_formatted": format_count(views),
            "country": {"manga": "JP", "manhwa": "KR", "manhua": "CN"}.get(
                self.type or "manga", "JP"
            ),
            "banner_image": cover,
            "scrape_layout": self.scrape_layout or {},
            "auto_scrape_enabled": (
                bool(self.auto_scrape_enabled)
                if self.auto_scrape_enabled is not None
                else True
            ),
            "scrape_frequency": scrape_frequency_label(interval_hours),
            "scrape_interval_value": interval_value,
            "scrape_interval_unit": interval_unit,
            "next_scrape_at": (
                self.next_check_at.isoformat()
                if self.next_check_at and self.auto_scrape_enabled is not False
                else None
            ),
            "last_scraped_at": (
                self.last_scraped.isoformat() if self.last_scraped else None
            ),
        }


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        Index("ix_chapters_manga_id_chapter_number", "manga_id", "chapter_number"),
    )
    id = Column(Integer, primary_key=True, index=True)
    manga_id = Column(Integer, ForeignKey("manga.id"), nullable=False)
    chapter_number = Column(DECIMAL(precision=10, scale=2), nullable=False)
    chapter_title = Column(String, nullable=True)
    # Translated subtitle per reader language ({"en": "..."}), filled lazily
    # by services.chapter_title_service; the raw source title stays above.
    title_translations = Column(JSON, nullable=True)
    chapter_url = Column(String, unique=True, nullable=False)
    scraped_at = Column(DateTime, nullable=True)
    pages = Column(JSON, nullable=True)
    # The source site's image URLs, kept when ``pages`` holds our own
    # compressed WebP copies (used to re-mirror, remap and roll back).
    source_pages = Column(JSON, nullable=True)
    # When this chapter merges several source chapters (one-page chapters
    # grouped in fives or tens): ``[{"url": ..., "number": ...}, ...]`` in
    # reading order. ``chapter_url`` is the first member's URL.
    group_urls = Column(JSON, nullable=True)
    # Bytes stored for this chapter's mirrored pages (storage accounting).
    pages_bytes = Column(Integer, nullable=True)
    # queued | scraping | complete | failed (SRS 1G.1.3). Chapters ingest one
    # by one (1G.2.3); this makes partial ingestion resumable and visible.
    ingestion_status = Column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    views = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(
        DateTime, nullable=True, default=datetime.utcnow, server_default=func.now()
    )

    manga = relationship("Manga", lazy="selectin", back_populates="chapters")
    read_history_entries = relationship(
        "ReadHistory",
        lazy="selectin",
        back_populates="chapter",
        cascade="all, delete-orphan",
    )
    bookmarks = relationship(
        "Bookmark",
        lazy="selectin",
        back_populates="chapter",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        raw_pages = self.pages or []
        if isinstance(raw_pages, list):
            pages = list(raw_pages)
        elif raw_pages:
            pages = [raw_pages]
        else:
            pages = []
        released = self.created_at or self.scraped_at
        number = chapter_number_value(self.chapter_number)
        return {
            "id": self.id,
            "manga_id": self.manga_id,
            "chapter_number": number,
            "chapter_title": self.chapter_title,
            "title": _display_title(self.chapter_title, number),
            "chapter_url": self.chapter_url,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "release_date": released.isoformat() if released else None,
            "views": int(self.views or 0),
            "pages": pages,
            "ingestion_status": self.ingestion_status or "queued",
        }


class ReadHistory(Base):
    __tablename__ = "read_history"
    __table_args__ = (
        Index("ix_read_history_user_id_last_read_at", "user_id", "last_read_at"),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    manga_id = Column(Integer, ForeignKey("manga.id"))
    chapter_id = Column(Integer, ForeignKey("chapters.id"))
    last_read_at = Column(DateTime, nullable=False, server_default=func.now())

    user = relationship("User", lazy="selectin", back_populates="read_history")
    manga = relationship(
        "Manga", lazy="selectin", back_populates="read_history_entries"
    )
    chapter = relationship(
        "Chapter", lazy="selectin", back_populates="read_history_entries"
    )


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (Index("ix_bookmarks_user_id_manga_id", "user_id", "manga_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    manga_id = Column(Integer, ForeignKey("manga.id"))
    chapter_id = Column(Integer, ForeignKey("chapters.id"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    user = relationship("User", lazy="selectin", back_populates="bookmarks")
    manga = relationship("Manga", lazy="selectin", back_populates="bookmarks")
    chapter = relationship("Chapter", lazy="selectin", back_populates="bookmarks")
