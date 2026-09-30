"""Reader engagement: ratings, chapter likes, broken-chapter reports, site
announcements and per-day view counters."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)

from .base import Base


class MangaRating(Base):
    __tablename__ = "manga_ratings"
    __table_args__ = (
        UniqueConstraint("manga_id", "user_id", name="uq_manga_ratings_manga_user"),
        CheckConstraint("score >= 1 AND score <= 10", name="ck_manga_ratings_score"),
    )

    id = Column(Integer, primary_key=True)
    manga_id = Column(
        Integer, ForeignKey("manga.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    score = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ChapterLike(Base):
    __tablename__ = "chapter_likes"
    __table_args__ = (
        UniqueConstraint("chapter_id", "user_id", name="uq_chapter_likes_chapter_user"),
    )

    id = Column(Integer, primary_key=True)
    chapter_id = Column(
        Integer,
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ChapterReport(Base):
    """A reader's "this chapter is broken" report (missing pages, wrong
    order, wrong chapter...). Open reports surface as an alert banner on the
    chapter until an administrator resolves them."""

    __tablename__ = "chapter_reports"
    __table_args__ = (Index("ix_chapter_reports_status_created", "status", "created_at"),)

    id = Column(Integer, primary_key=True)
    chapter_id = Column(
        Integer,
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manga_id = Column(
        Integer, ForeignKey("manga.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    report_type = Column(String(64), nullable=False)
    details = Column(Text, nullable=True)
    # open | resolved
    status = Column(String(16), nullable=False, default="open", server_default="open")
    resolved_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Announcement(Base):
    """Site-wide notice shown on the homepage ticker, optionally as a
    one-time popup."""

    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False, default="Announcement")
    message = Column(Text, nullable=False)
    # info | update | warning | event ... (free-form label the UI colours)
    type = Column(String(32), nullable=False, default="info", server_default="info")
    is_popup = Column(Boolean, nullable=False, default=False, server_default="false")
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class MangaDailyView(Base):
    """One row per series per UTC day; feeds the today/week/month rankings."""

    __tablename__ = "manga_daily_views"

    manga_id = Column(
        Integer, ForeignKey("manga.id", ondelete="CASCADE"), primary_key=True
    )
    day = Column(Date, primary_key=True)
    views = Column(Integer, nullable=False, default=0, server_default="0")


class AdminTaskResult(Base):
    """Outcome of a long admin action run by a background worker (series
    previews, parser generation). The admin page polls this row; the API
    process never runs the blocking scraper itself."""

    __tablename__ = "admin_task_results"

    id = Column(String(36), primary_key=True)
    kind = Column(String(32), nullable=False)
    requested_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # queued | running | done | failed
    status = Column(String(16), nullable=False, default="queued", server_default="queued")
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
