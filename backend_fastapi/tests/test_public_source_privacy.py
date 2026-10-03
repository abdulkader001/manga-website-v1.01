"""plan.md P1-1: visitors never see where the content comes from.

``/manga/batch`` returned the series' source, its last scrape error and who
added it; the chapter list and chapter routes carried each chapter's source
link; pictures not yet mirrored went out as raw source URLs or as a proxy
link whose base64 parameters spelled the source out.

The contract: seed a series whose every source address contains
``source.invalid``, call every public GET route as a guest and as a signed-in
reader, and that string appears in no response.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga
from backend_fastapi.app.services import image_proxy
from backend_fastapi.app.utils import swr_cache

from _support import staff
from _support.db_reset import clear_list_cache
from _support.route_table import route_table

MARK = "source.invalid"


@pytest.fixture
def leaky_series(fastapi_app):
    swr_cache._local_cache.clear()
    clear_list_cache()
    tag = uuid.uuid4().hex
    with SessionLocal() as session:
        manga = Manga(
            title=f"Privacy {tag}",
            slug=f"privacy-{tag[:12]}",
            source_url=f"https://{MARK}/series/{tag}",
            cover_image=f"https://{MARK}/covers/{tag}.jpg",
            mangaupdates_url=f"https://{MARK}/mu/{tag}",
            scrape_layout={"from": f"https://{MARK}/layout"},
            last_error=f"403 from https://{MARK}/series/{tag}",
            genres=["Action"],
            type="manga",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://{MARK}/series/{tag}/1",
            pages=[f"https://{MARK}/p/{tag}/1.jpg", f"https://{MARK}/p/{tag}/2.jpg"],
            source_pages=[f"https://{MARK}/p/{tag}/1.jpg"],
            group_urls=[f"https://{MARK}/group/{tag}"],
        )
        session.add(chapter)
        session.commit()
        return {"manga": manga.id, "chapter": chapter.id, "slug": manga.slug}


def _fill(path: str, ids: dict) -> str:
    def value(match: re.Match) -> str:
        name = match.group(1).split(":")[0].lower()
        if "chapter" in name:
            return str(ids["chapter"])
        if "manga" in name or "series" in name:
            return str(ids["manga"])
        if "slug" in name:
            return ids["slug"]
        return "1"

    return re.sub(r"\{([^}]+)\}", value, path)


def _public_get_paths(ids: dict) -> list[str]:
    paths = set()
    for route in route_table():
        if "GET" not in route.methods:
            continue
        if route.path.startswith("/admin") or "/stream" in route.path or "events" in route.path:
            continue
        paths.add(_fill(route.path, ids))
    return sorted(paths)


def test_no_public_get_shows_the_source(fastapi_client, leaky_series):
    ids = leaky_series
    paths = _public_get_paths(ids)
    extra = [
        f"/manga/batch?ids={ids['manga']}",
        "/manga/?per_page=90&q=Privacy",
        f"/manga/{ids['manga']}/chapters?order=desc",
    ]
    leaks = []
    for headers in ({}, staff.headers(staff.reader())):
        for path in paths + extra:
            response = fastapi_client.get(f"/api/v1{path}", headers=headers)
            if MARK in response.text:
                who = "reader" if headers else "guest"
                leaks.append(f"{who} GET {path} -> {response.status_code}")
    # The routes the old code leaked through must really have been called.
    assert any(p.startswith("/manga/batch") for p in extra)
    assert not leaks, "the source shows in:\n" + "\n".join(leaks)


def test_reader_pages_are_opaque_tokens(fastapi_client, leaky_series):
    response = fastapi_client.get(
        f"/api/v1/manga/{leaky_series['manga']}/chapters/{leaky_series['chapter']}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "chapter_url" not in body
    assert len(body["pages"]) == 2
    for page in body["pages"]:
        assert page.startswith(image_proxy.PROXY_PATH + "?t=")
        assert "u=" not in page
        token = parse_qs(urlsplit(page).query)["t"][0]
        url, _ = image_proxy.decode_token(token)
        assert url.startswith(f"https://{MARK}/p/")


def test_staff_still_see_sources(fastapi_client, leaky_series):
    owner = staff.owner()
    response = fastapi_client.get(f"/api/v1/manga/{leaky_series['manga']}", headers=staff.headers(owner))
    assert response.status_code == 200
    assert response.json()["source_url"].startswith(f"https://{MARK}/series/")


def test_batch_keeps_only_public_fields(fastapi_client, leaky_series):
    response = fastapi_client.get(f"/api/v1/manga/batch?ids={leaky_series['manga']}")
    assert response.status_code == 200
    (item,) = response.json()["items"]
    for field in ("source_url", "last_error", "added_by", "check_interval_hours", "scrape_layout"):
        assert field not in item or not item[field], field
    assert item["first_chapter_id"] == leaky_series["chapter"]
    assert item["latest_chapter_id"] == leaky_series["chapter"]


def test_list_and_detail_carry_chapter_ids(fastapi_client, leaky_series):
    """plan.md P1-5: the response model dropped first/latest chapter ids."""

    listing = fastapi_client.get("/api/v1/manga/", params={"per_page": 90, "q": "Privacy"})
    detail = fastapi_client.get(f"/api/v1/manga/{leaky_series['manga']}")
    item = next(i for i in listing.json()["items"] if i["id"] == leaky_series["manga"])
    for body in (item, detail.json()):
        assert body["first_chapter_id"] == leaky_series["chapter"]
        assert body["latest_chapter_id"] == leaky_series["chapter"]


def test_proxy_token_cannot_be_forged_or_read():
    link = image_proxy.opaque_url("https://source.invalid/a.jpg", "https://source.invalid/")
    token = parse_qs(urlsplit(link).query)["t"][0]
    assert MARK not in token
    assert image_proxy.decode_token(token) == ("https://source.invalid/a.jpg", "https://source.invalid/")
    assert image_proxy.decode_token(token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]) is None
    assert image_proxy.decode_token("not-a-token") is None


def test_proxy_refuses_a_bad_token(fastapi_client):
    response = fastapi_client.get("/api/v1/images/proxy", params={"t": "forged"})
    assert response.status_code == 403
