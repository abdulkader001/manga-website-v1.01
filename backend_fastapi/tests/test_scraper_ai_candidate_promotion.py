"""F-21 (AI-fallback candidate promotion) and F-23 (chapter-number parse warning).

F-21: the mid-scrape AI fallback (``BaseScraper._ai_fallback``) used to persist
a successful config to the orphaned ``scraper_config_pending_ai_<domain>``
Setting key -- nothing ever read it, so it had no path into production. It now
registers a ``ParserVersion`` candidate (source=ai_generated) instead, reusing
the same PA-approval lifecycle every other parser source already goes through
(``parser_versions_service``), which is directly promotable via the existing
``GET /admin/parsers/{domain}`` / ``POST /admin/parsers/versions/{id}/approve``
endpoints with no new admin surface.

F-23: a ``chapter_number`` selector match that fails ``float()`` parsing used
to silently become chapter ``0.0`` with no trace.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import ParserVersion, User, UserRole
from backend_fastapi.app.scrapers import base_scraper as base_scraper_module
from backend_fastapi.app.scrapers.base_scraper import BaseScraper
from backend_fastapi.app.scrapers.config import ConfigManager
from backend_fastapi.app.services import parser_versions_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


MANGA_SELECTORS = {
    "manga_title": "h1.title",
    "manga_description": ".desc",
    "manga_cover": "img.cover",
    "chapter_list": "ul.ch li",
    "chapter_url": "a",
    "chapter_title": "span.t",
    "chapter_number": "span.n",
}


class _Tag:
    def __init__(self, text="", attrs=None):
        self._text = text
        self._attrs = attrs or {}

    @property
    def text(self):
        return self._text

    def get(self, key):
        return self._attrs.get(key)


class _ChapterItem:
    def __init__(self, mapping):
        self._mapping = mapping

    def select_one(self, sel):
        return self._mapping.get(sel)


class _FakeSoup:
    def __init__(self, chapter_number_text: str):
        self._chapter_item = _ChapterItem(
            {
                "a": _Tag(attrs={"href": "/manga/alpha/ch-3"}),
                "span.t": _Tag("Chapter 3"),
                "span.n": _Tag(chapter_number_text),
            }
        )

    def select_one(self, sel):
        return {
            "h1.title": _Tag("Alpha Series"),
            ".desc": _Tag("A description"),
            "img.cover": _Tag(attrs={"src": "https://x.example/cover.jpg"}),
        }.get(sel)

    def select(self, sel):
        return [self._chapter_item] if sel == "ul.ch li" else []

    def __str__(self):
        return "<html></html>"


def _candidates(domain):
    session = SessionLocal()
    try:
        return session.query(ParserVersion).filter(ParserVersion.domain == domain).all()
    finally:
        session.close()


def _make_pa(session) -> int:
    admin = User(
        email=f"pa-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="PA",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin.id


def test_ai_fallback_success_registers_promotable_candidate():
    domain = f"f21-{uuid.uuid4().hex[:8]}.example"
    scraper = BaseScraper(domain)
    scraper.config = None  # no stored parser -- forces the AI fallback

    with mock.patch.object(
        BaseScraper, "_fetch_html", return_value=_FakeSoup("3")
    ), mock.patch.object(BaseScraper, "_ai_fallback", return_value=MANGA_SELECTORS):
        result = scraper.scrape_manga(f"https://{domain}/manga/alpha")

    assert result["title"] == "Alpha Series"

    versions = _candidates(domain)
    assert len(versions) == 1
    version = versions[0]
    assert version.status == "candidate"
    assert version.source == "ai_generated"
    assert version.definition == MANGA_SELECTORS
    assert version.test_results == {"title_found": True, "chapters_found": 1}

    # Exactly the promotion path F-21 asked for: the candidate is listable and
    # approvable through the pre-existing generic parser-version lifecycle,
    # with no bespoke admin endpoint required for the AI-fallback source.
    session = SessionLocal()
    try:
        pa_id = _make_pa(session)
        activated = parser_versions_service.activate(session, version.id, actor_id=pa_id)
        session.commit()
    finally:
        session.close()

    assert activated.status == "active"
    assert ConfigManager.get_config(domain) == MANGA_SELECTORS


def test_repeated_ai_fallback_does_not_spam_duplicate_candidates():
    domain = f"f21dup-{uuid.uuid4().hex[:8]}.example"
    scraper = BaseScraper(domain)
    scraper.config = None

    with mock.patch.object(
        BaseScraper, "_fetch_html", return_value=_FakeSoup("3")
    ), mock.patch.object(BaseScraper, "_ai_fallback", return_value=MANGA_SELECTORS):
        scraper.scrape_manga(f"https://{domain}/manga/alpha")
        scraper.scrape_manga(f"https://{domain}/manga/alpha")

    # Every scrape of an unpromoted domain re-triggers the fallback (self.config
    # is never mutated in-place); without dedup this would spam one row per scrape.
    assert len(_candidates(domain)) == 1


def test_unparseable_chapter_number_logs_warning_with_raw_string():
    domain = f"f23-{uuid.uuid4().hex[:8]}.example"
    scraper = BaseScraper(domain)
    scraper.config = MANGA_SELECTORS  # stored config present -- no AI fallback

    with mock.patch.object(
        BaseScraper, "_fetch_html", return_value=_FakeSoup("Extra")
    ), mock.patch.object(base_scraper_module, "logger") as mock_logger:
        result = scraper.scrape_manga(f"https://{domain}/manga/alpha")

    assert result["chapters"][0]["number"] == 0.0
    assert mock_logger.warning.called
    logged = " ".join(str(c) for c in mock_logger.warning.call_args_list)
    assert "Extra" in logged
    assert domain in logged

    # No stored config -- the parse failure is not an AI-fallback event.
    assert _candidates(domain) == []
