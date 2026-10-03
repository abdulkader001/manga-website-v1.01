from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    ForeignKey,
    func,
    Index,
    JSON,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    url = Column(String, unique=True, nullable=False)
    provider = Column(String(100), nullable=True)
    schedule = Column(String(50), nullable=True)  # e.g. cron-style alias
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    scraping_jobs = relationship(
        "ScrapingJob", lazy="selectin", back_populates="source"
    )


class ApprovedSourceDomain(Base):
    """A source website approved by the Permanent Administrator (SRS 1G.1.1).

    Saving a row here IS the approval (1G.6.0); nothing from a domain can be
    scraped until its row exists, no matter what parsers exist (1G.3).
    """

    __tablename__ = "approved_source_domains"

    id = Column(Integer, primary_key=True)
    base_url = Column(String(512), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)
    label = Column(String(255), nullable=True)
    # ----- Website lifecycle (SRS 1G.6.3) ------------------------------
    # pending -> testing -> active -> degraded/disabled. ``active`` means
    # manga URL submission is open for this website.
    status = Column(
        String(16), nullable=False, default="active", server_default="active"
    )
    # Original language(s) of the site's content (1G.6.2): ja/zh/ko/other.
    original_languages = Column(JSON, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    # Politeness limit for this site: max requests per minute (1G.1.1).
    request_rate_limit = Column(Integer, nullable=True)
    last_health_check = Column(DateTime, nullable=True)
    # Scheduled new-chapter check settings (SRS 1G.12A.4): interval_hours,
    # jitter_hours, max_concurrent, quiet_hours ([start,end] hour ints),
    # enabled. Defaults applied in scheduled_checks_service when absent.
    check_settings = Column(JSON, nullable=True)
    # ----- Website-level content rights (SRS 1J) -----------------------
    # Defaults for every series ingested from this website. ``may_host`` and
    # ``may_translate`` are separate permissions; a series can never exceed what
    # its source website grants (the two are ANDed together when rights are
    # resolved). ``attribution`` is the credit line the website's licence
    # requires us to display.
    may_host = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    may_translate = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    attribution = Column(String(512), nullable=True)
    license = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "base_url": self.base_url,
            "domain": self.domain,
            "label": self.label,
            "status": self.status or "active",
            "original_languages": self.original_languages or [],
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "request_rate_limit": self.request_rate_limit,
            "last_health_check": (
                self.last_health_check.isoformat() if self.last_health_check else None
            ),
            "may_host": bool(self.may_host) if self.may_host is not None else True,
            "may_translate": (
                bool(self.may_translate) if self.may_translate is not None else True
            ),
            "attribution": self.attribution,
            "license": self.license,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ScrapingJob(Base):
    __tablename__ = "scraping_jobs"
    __table_args__ = (
        Index("ix_scraping_jobs_status_updated_at", "status", "updated_at"),
    )
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    manga_id = Column(Integer, ForeignKey("manga.id", ondelete="SET NULL"), nullable=True)
    source_url = Column(String, nullable=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    error = Column(Text, nullable=True)
    # Structured failure detail (SRS 1G.5.4): url, missing_field, selector,
    # scraper module — enough to diagnose without reproducing.
    error_details = Column(JSON, nullable=True)
    # Who submitted the manga URL (1G.1.2 added_by; copied to the series).
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Everyone who clicked Fix while this job was running (1G.12.2A) — all of
    # them get the completion notification, not just the first clicker.
    subscribers = Column(JSON, nullable=True)
    last_chapter_number = Column(String, nullable=True)
    # What the submitter asked for beyond the URL: MangaUpdates metadata, the
    # series type, schedule, and a cap on how many chapters to ingest. Applied
    # when the series record is created (after extraction succeeded).
    options = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    source = relationship("Source", lazy="selectin", back_populates="scraping_jobs")

    manga = relationship("Manga", lazy="selectin", back_populates="scraping_jobs")


class ParserVersion(Base):
    """A versioned parser definition for one website (SRS 1G.8.5).

    ``definition`` holds everything website-specific — selectors, metadata
    mapping, request behaviour, quirks (1G.7.6). Exactly one version per domain
    is ``active`` at a time (enforced in the service layer); prior versions are
    retained as ``retired`` for one-action rollback. AI-generated, manual, and
    rule-based parsers all flow through the same candidate -> approval path
    (1G.8.3 / 1G.10 / 1G.11).
    """

    __tablename__ = "parser_versions"
    __table_args__ = (
        UniqueConstraint("domain", "version", name="uq_parser_versions_domain_version"),
        Index("ix_parser_versions_domain_status", "domain", "status"),
    )

    id = Column(Integer, primary_key=True)
    domain = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    # candidate | active | retired | rejected
    status = Column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    # ai_generated | manual | rules (1G.8 / 1G.10 / 1G.11)
    source = Column(String(16), nullable=False, default="manual")
    definition = Column(JSON, nullable=False)
    # Test results attached to the version so a later reviewer can see what it
    # was verified against (1G.8.5).
    test_results = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def module_id(self) -> str:
        """Version identity, e.g. ``example.com_v3`` (1G.8.5)."""
        return f"{self.domain}_v{self.version}"

    def to_dict(self):
        return {
            "id": self.id,
            "domain": self.domain,
            "version": self.version,
            "module_id": self.module_id,
            "status": self.status,
            "source": self.source,
            "definition": self.definition or {},
            "test_results": self.test_results,
            "notes": self.notes,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
