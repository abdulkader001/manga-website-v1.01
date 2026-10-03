"""Admin -> Error Report: errors the site hit, grouped, with a likely cause and fix.

Owner's request (2026-10-03): one admin tab that shows what kind of error is
happening, what the real problem is and how to fix it. Errors come from three
places: the API server (unhandled exceptions and 5xx API errors), the
background workers (tasks that failed for good) and readers' browsers (script
errors and crashed pages, reported by ``src/utils/errorReporter.js``).

The same error is one row (``fingerprint``) with a count, so a crash that
happens a thousand times is one entry. Nothing that identifies a visitor is
stored: no IP address, no account, no query string; e-mails and tokens are
masked out of the message and stack before they are saved
(``services/error_report_service.scrub``).
"""

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, func, text

from .base import Base

SOURCE_SERVER = "server"
SOURCE_WORKER = "worker"
SOURCE_BROWSER = "browser"
SOURCES = (SOURCE_SERVER, SOURCE_WORKER, SOURCE_BROWSER)


class ErrorReport(Base):
    __tablename__ = "error_reports"

    id = Column(Integer, primary_key=True)
    # sha256 of source + kind + the message with numbers/ids taken out + where.
    fingerprint = Column(String(64), nullable=False, unique=True)
    source = Column(String(16), nullable=False)
    # Exception class, API error code or browser error name.
    kind = Column(String(128), nullable=False)
    message = Column(Text, nullable=True)
    # "GET /api/v1/manga/{id}", a task name, or a page path.
    location = Column(String(255), nullable=True)
    stack = Column(Text, nullable=True)
    category = Column(String(32), nullable=False, server_default="unknown")
    cause = Column(Text, nullable=True)
    fix = Column(Text, nullable=True)
    count = Column(Integer, nullable=False, server_default=text("1"), default=1)
    first_seen = Column(DateTime, nullable=False, server_default=func.now())
    last_seen = Column(DateTime, nullable=False, server_default=func.now())
    resolved = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, nullable=True)

    __table_args__ = (Index("ix_error_reports_last_seen", "last_seen"),)
