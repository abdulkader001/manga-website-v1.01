"""Fetching like a browser, waiting when asked, taking the biggest picture.

Techniques the well-known open-source downloaders use (gallery-dl, Mihon /
Tachiyomi extensions, HakuNeko): one current browser identity per site with
the usual browser headers, honouring ``Retry-After``, retrying picture
downloads that hit a burst limit, and reading the full-size entry of a
responsive image instead of its small ``src`` fallback.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from backend_fastapi.app.scrapers import http_client, parsing
from backend_fastapi.app.services import page_image_service as pis


def test_one_current_browser_identity_per_site():
    first = http_client.user_agent_for("https://www.site.example/a")
    assert first == http_client.user_agent_for("https://site.example/b/c")
    assert "Chrome/1" in first or "Firefox/1" in first
    assert all("Chrome/119" not in ua for ua in http_client.USER_AGENTS)


def test_requests_carry_browser_headers_without_overriding_the_parser():
    headers = http_client._with_browser_headers("https://site.example/", {"accept-language": "ko"})
    assert headers["User-Agent"] == http_client.user_agent_for("https://site.example/")
    assert headers["accept-language"] == "ko" and "Accept-Language" not in headers
    assert headers["Accept"].startswith("text/html")


def test_retry_after_is_honoured_and_capped():
    response = requests.Response()
    response.headers["Retry-After"] = "7"
    assert http_client.retry_after_seconds(response, 2) == 7
    response.headers["Retry-After"] = "999"
    assert http_client.retry_after_seconds(response, 2, cap=30) == 30
    response.headers["Retry-After"] = "Wed, 21 Oct 2026 07:28:00 GMT"
    assert http_client.retry_after_seconds(response, 2) == 2


def _tag(html: str):
    return BeautifulSoup(html, "html.parser").find("img")


def test_the_largest_srcset_picture_beats_the_small_src():
    tag = _tag('<img src="/p/1-300x450.jpg" srcset="/p/1-300x450.jpg 300w, /p/1.jpg 1200w, /p/1-768x1152.jpg 768w">')
    assert parsing.image_url(tag, "https://s.example/ch/1") == "https://s.example/p/1.jpg"


def test_lazy_attributes_still_come_first_and_plain_images_are_unchanged():
    lazy = _tag('<img src="/blank.gif" data-src="/p/real.jpg" srcset="/p/small.jpg 300w">')
    assert parsing.image_url(lazy, "https://s.example/") == "https://s.example/p/real.jpg"
    plain = _tag('<img src="/p/2.jpg">')
    assert parsing.image_url(plain, "https://s.example/") == "https://s.example/p/2.jpg"


def test_picture_downloads_retry_after_a_burst_limit(monkeypatch):
    answers = [429, 503, 200]
    waits: list = []

    def fake_get(url, *args, **kwargs):
        response = requests.Response()
        response.status_code = answers.pop(0)
        response.headers["Retry-After"] = "1"
        response._content = b"picture"
        return response

    monkeypatch.setattr("backend_fastapi.app.scrapers.http_client.RequestWrapper.get", staticmethod(fake_get))
    monkeypatch.setattr(pis.time, "sleep", waits.append)
    assert pis._download("https://img.example/1.jpg", None, None) == b"picture"
    assert waits == [1.0, 1.0]


def test_a_missing_picture_is_not_retried(monkeypatch):
    calls: list = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 404
        return response

    monkeypatch.setattr("backend_fastapi.app.scrapers.http_client.RequestWrapper.get", staticmethod(fake_get))
    monkeypatch.setattr(pis.time, "sleep", lambda s: None)
    try:
        pis._download("https://img.example/gone.jpg", None, None)
    except ValueError as exc:
        assert "404" in str(exc)
    assert len(calls) == 1
