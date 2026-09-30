"""AI parser generation workflow (SRS 1G.8.2 / 1G.8.3 / 1G.9).

Covers: the full generate-and-test flow against a listing page, a series
page, and two chapter pages; the result is a CANDIDATE (never activated);
honest failure — with the exact 1G.9.2 statement — whenever any step cannot
be completed, including a parser that passes one chapter page but fails the
other (1G.9.4); and the unconfigured-AI notification path.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import Notification, ParserVersion
from backend_fastapi.app.services import (
    parser_generation_service,
    scraper_ai_service,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


LISTING_HTML = """
<html><body>
  <a href="/manga/alpha">Alpha</a>
  <a href="/about">About</a>
  <a href="https://other-site.com/manga/x">External</a>
</body></html>
"""

SERIES_HTML = """
<html><body>
  <h1 class="title">Alpha Series</h1>
  <ul class="ch">
    <li><a href="/manga/alpha/ch-2">Chapter 2</a></li>
    <li><a href="/manga/alpha/ch-1">Chapter 1</a></li>
  </ul>
</body></html>
"""

CHAPTER_HTML_OK = """
<html><body><div class="pages">
  <img src="/img/p1.jpg"/><img src="/img/p2.jpg"/>
</div></body></html>
"""

CHAPTER_HTML_EMPTY = "<html><body><div class='pages'></div></body></html>"

SERIES_SELECTORS = {
    "manga_title": "h1.title",
    "manga_description": ".desc",
    "manga_cover": "img.cover",
    "chapter_list": "ul.ch li",
    "chapter_url": "a",
    "chapter_title": "a",
    "chapter_number": "a",
}
CHAPTER_SELECTORS = {"page_images": ".pages img"}


def _page_map(domain: str, *, second_chapter_html: str = CHAPTER_HTML_OK) -> dict:
    return {
        f"https://{domain}": LISTING_HTML,
        f"https://{domain}/manga/alpha": SERIES_HTML,
        f"https://{domain}/manga/alpha/ch-2": CHAPTER_HTML_OK,
        f"https://{domain}/manga/alpha/ch-1": second_chapter_html,
    }


def _mock_ai(html, type):
    return SERIES_SELECTORS if type == "manga" else CHAPTER_SELECTORS


def _run(domain: str, pages: dict, *, ai=_mock_ai, configured=True):
    session = SessionLocal()
    try:
        with mock.patch.object(
            parser_generation_service, "_fetch_html", side_effect=pages.get
        ):
            with mock.patch.object(
                scraper_ai_service, "is_configured", return_value=configured
            ):
                with mock.patch.object(
                    scraper_ai_service, "generate_selectors", side_effect=ai
                ):
                    return parser_generation_service.attempt_generation(
                        session,
                        domain=domain,
                        base_url=f"https://{domain}",
                    )
    finally:
        session.close()


def _notes(type_: str, domain: str) -> list:
    session = SessionLocal()
    try:
        return [
            n
            for n in session.query(Notification)
            .filter(Notification.type == type_)
            .all()
            if (n.data or {}).get("domain") == domain
        ]
    finally:
        session.close()


def test_successful_generation_registers_candidate_only():
    domain = f"gen-{uuid.uuid4().hex[:6]}.com"
    result = _run(domain, _page_map(domain))
    assert result["status"] == "candidate"

    session = SessionLocal()
    try:
        version = (
            session.query(ParserVersion).filter(ParserVersion.domain == domain).one()
        )
        # 1G.8.3: never auto-activated.
        assert version.status == "candidate"
        assert version.source == "ai_generated"
        # 1G.8.5: the test results are stored on the version.
        tests = version.test_results
        assert tests["series_page"]["passed"] is True
        assert tests["series_page"]["title"] == "Alpha Series"
        assert len(tests["chapter_pages"]) == 2
        assert all(t["passed"] for t in tests["chapter_pages"])
    finally:
        session.close()

    assert _notes("parser.candidate_ready", domain)


def test_partial_pass_is_failure():
    """A parser that passes on one chapter page and fails on another is a
    failure, not a success (1G.9.4)."""
    domain = f"part-{uuid.uuid4().hex[:6]}.com"
    result = _run(domain, _page_map(domain, second_chapter_html=CHAPTER_HTML_EMPTY))
    assert result["status"] == "failed"
    assert result["report"]["failed_step"] == "test_chapter_pages"
    assert result["report"]["message"] == scraper_ai_service.HONEST_FAILURE_MESSAGE

    # No candidate registered.
    session = SessionLocal()
    try:
        assert (
            session.query(ParserVersion).filter(ParserVersion.domain == domain).count()
            == 0
        )
    finally:
        session.close()

    notes = _notes("parser.generation_failed", domain)
    assert notes
    assert scraper_ai_service.HONEST_FAILURE_MESSAGE in notes[0].body
    # 1G.9.3: the notification asks for exactly what is needed.
    assert "A sample chapter page URL" in notes[0].body


def test_homepage_without_series_links_fails_honestly():
    domain = f"bare-{uuid.uuid4().hex[:6]}.com"
    pages = {f"https://{domain}": "<html><body><p>No links.</p></body></html>"}
    result = _run(domain, pages)
    assert result["status"] == "failed"
    assert result["report"]["failed_step"] == "discover_series_page"
    assert result["report"]["message"] == scraper_ai_service.HONEST_FAILURE_MESSAGE


def test_single_chapter_series_fails_two_page_requirement():
    """1G.8.2 requires testing at least TWO chapter pages."""
    domain = f"one-{uuid.uuid4().hex[:6]}.com"
    one_chapter_series = SERIES_HTML.replace(
        '<li><a href="/manga/alpha/ch-1">Chapter 1</a></li>', ""
    )
    pages = _page_map(domain)
    pages[f"https://{domain}/manga/alpha"] = one_chapter_series
    result = _run(domain, pages)
    assert result["status"] == "failed"
    assert result["report"]["failed_step"] == "insufficient_chapter_pages"


def test_unconfigured_ai_notifies_instead_of_silence():
    domain = f"noai-{uuid.uuid4().hex[:6]}.com"
    result = _run(domain, _page_map(domain), configured=False)
    assert result["status"] == "not_configured"
    notes = _notes("parser.needed", domain)
    assert notes
    assert "no scraper-generation AI is configured" in notes[0].body


def test_fetch_html_is_ssrf_hardened():
    """1H.4: parser generation fetches a PA-supplied homepage URL — it must
    route through the same SSRF-validated, redirect-safe client the
    production scraper uses (app.scrapers.http_client.RequestWrapper), not a
    bare requests.get that would follow a redirect into internal ranges or
    the cloud metadata endpoint."""
    with mock.patch(
        "backend_fastapi.app.scrapers.http_client.RequestWrapper.get"
    ) as wrapped_get:
        wrapped_get.return_value = mock.Mock(
            text="<html></html>", raise_for_status=lambda: None
        )
        result = parser_generation_service._fetch_html("https://example.com")
    assert result == "<html></html>"
    assert wrapped_get.called


def test_fetch_html_rejects_internal_targets():
    """A homepage URL pointing at a private/loopback address or the cloud
    metadata endpoint must never be fetched."""
    for blocked_url in (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
    ):
        result = parser_generation_service._fetch_html(blocked_url)
        assert result is None, f"{blocked_url} should have been blocked"


def test_manual_generate_endpoint_dispatches_async_not_inline(fastapi_client):
    """F-20: POST /admin/parsers/{domain}/generate must dispatch to the same
    Celery task its auto-triggered (website-saved) twin already uses,
    rather than running attempt_generation's multi-fetch,
    multi-AI-provider-call chain synchronously inside the request handler.
    """
    from backend_fastapi.app.core.security import create_access_token
    from backend_fastapi.app.models import ApprovedSourceDomain, User, UserRole

    domain = f"manual-gen-{uuid.uuid4().hex[:8]}.example"
    session = SessionLocal()
    try:
        session.add(
            ApprovedSourceDomain(
                domain=domain, base_url=f"https://{domain}", status="active"
            )
        )
        admin = User(
            email=f"pa-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="PA",
            role=UserRole.PERMANENT,
            is_main_admin=True,
            is_secondary_admin=True,
            permanent=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    with mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.generate_parser_task.delay"
    ) as delay, mock.patch.object(
        parser_generation_service, "attempt_generation"
    ) as attempt:
        delay.return_value = mock.Mock(id="task-123")
        resp = fastapi_client.post(
            f"/api/admin/parsers/{domain}/generate", headers=headers
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["domain"] == domain
    # Dispatched async with the domain's base_url and the "repair" trigger.
    # series_url/chapter_urls are the optional 1G.9.3 operator-supplied samples,
    # None here since this request sent no body.
    delay.assert_called_once_with(
        domain,
        f"https://{domain}",
        "repair",
        series_url=None,
        chapter_urls=None,
    )
    # The synchronous, request-blocking call must not happen anymore.
    attempt.assert_not_called()
