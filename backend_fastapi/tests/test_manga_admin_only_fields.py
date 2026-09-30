"""Scraping sources are visible to admins only."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Manga, User, UserRole
from backend_fastapi.app.utils import swr_cache

HIDDEN = ("source_url", "mangaupdates_url", "scrape_layout")


@pytest.fixture
def series(db_session):
    swr_cache._local_cache.clear()
    manga = Manga(
        title="Hidden Sources",
        slug=f"hidden-sources-{uuid.uuid4().hex[:8]}",
        source_url=f"https://example.com/manga/{uuid.uuid4().hex}",
        mangaupdates_url="https://www.mangaupdates.com/series/abc/x",
        scrape_layout={"group_size": 5},
        type="manga",
        genres=["action"],
    )
    db_session.add(manga)
    db_session.commit()
    return manga.id


def _headers(role: UserRole, *, main: bool = False) -> dict[str, str]:
    with SessionLocal() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=role,
            is_main_admin=main,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _responses(client, manga_id, headers, per_page):
    detail = client.get(f"/api/v1/manga/{manga_id}", headers=headers)
    listing = client.get(
        "/api/v1/manga/", params={"per_page": per_page}, headers=headers
    )
    assert detail.status_code == 200
    assert listing.status_code == 200
    items = [i for i in listing.json()["items"] if i["id"] == manga_id]
    assert items
    return [detail.json(), items[0]]


def test_visitor_and_user_do_not_see_sources(fastapi_client, series):
    for headers in ({}, _headers(UserRole.USER)):
        for body in _responses(fastapi_client, series, headers, 90):
            for field in HIDDEN:
                assert not body.get(field), field


def test_admin_sees_sources_even_after_a_visitor_warmed_the_cache(fastapi_client, series):
    # Same query and same cached payload: a visitor's stripped copy must not
    # leak into the admin's response.
    _responses(fastapi_client, series, {}, 90)
    headers = _headers(UserRole.ADMIN, main=True)
    for body in _responses(fastapi_client, series, headers, 90):
        assert body["source_url"].startswith("https://example.com/manga/")
        assert body["mangaupdates_url"]
        assert body["scrape_layout"] == {"group_size": 5}
