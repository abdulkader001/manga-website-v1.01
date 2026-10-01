"""MangaUpdates / Anime-Planet metadata links and the one-series-one-link rule."""

from __future__ import annotations

import json
import uuid

import pytest

from backend_fastapi.app.core.api_errors import ApiError
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Manga, User, UserRole
from backend_fastapi.app.services import animeplanet_service as ap
from backend_fastapi.app.services import metadata_sources as ms
from backend_fastapi.app.services import series_import

URL = "https://www.anime-planet.com/manga/on-the-way-to-meet-mom"


def _page(kind="Manhwa", *, jsonld=True, status="Completed"):
    ld = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": "On the Way to Meet Mom",
        "description": "A boy sets out to find his mother.",
        "image": "https://cdn.example/cover.jpg",
        "genre": ["Drama", "Slice of Life"],
        "author": [{"@type": "Person", "name": "Some Author"}],
        "datePublished": "2019-05-01",
    }
    return f"""<html><head><title>On the Way to Meet Mom | Manga | Anime-Planet</title>
    <meta property="og:image" content="https://cdn.example/og.jpg">
    {'<script type="application/ld+json">' + json.dumps(ld) + '</script>' if jsonld else ''}
    </head><body><h1>On the Way to Meet Mom</h1>
    <section class="pure-g entryBar"><div><span>Type:</span> <span>{kind}</span></div>
    <div>Status: {status}</div></section>
    <a href="/manga/tags/drama">Drama</a></body></html>"""


@pytest.mark.parametrize(("kind", "expected"), [("Manga", "manga"), ("Manhwa", "manhwa"), ("Webtoon", "manhwa"), ("Manhua", "manhua")])
def test_manga_types_are_accepted(kind, expected):
    meta = ap.parse_page(_page(kind), URL)
    assert meta.type == expected
    assert meta.title == "On the Way to Meet Mom"
    assert meta.genres == ["Drama", "Slice of Life"]
    assert meta.authors == ["Some Author"]
    assert meta.cover_url == "https://cdn.example/cover.jpg"
    assert meta.status == "completed"
    assert meta.url == URL


@pytest.mark.parametrize("kind", ["Light Novel", "Web Novel", "Novel", "TV Series", "Anime"])
def test_novels_and_anime_are_refused(kind):
    with pytest.raises(ap.AnimePlanetError) as exc:
        ap.parse_page(_page(kind), URL)
    assert "Only manga, manhwa and manhua" in str(exc.value)


def test_falls_back_to_open_graph_without_json_ld():
    meta = ap.parse_page(_page("Manhua", jsonld=False), URL)
    assert meta.title == "On the Way to Meet Mom"
    assert meta.cover_url == "https://cdn.example/og.jpg"
    assert meta.type == "manhua"


@pytest.mark.parametrize(
    "bad",
    [
        "https://www.anime-planet.com/anime/naruto",
        "https://www.anime-planet.com/manga/all",
        "https://www.anime-planet.com/manga/tags/drama",
        "https://evil.example/manga/on-the-way-to-meet-mom",
        "https://www.anime-planet.com.evil.example/manga/x",
    ],
)
def test_only_single_manga_pages_on_anime_planet(bad):
    with pytest.raises(ap.AnimePlanetError):
        ap.slug_from_url(bad)


def test_identity_is_stable_across_spellings():
    assert ms.identity("https://www.anime-planet.com/manga/On-The-Way-To-Meet-Mom/") == ("animeplanet", "on-the-way-to-meet-mom")
    assert ms.identity("https://www.mangaupdates.com/series/pi4azuo/solo-leveling") == ms.identity(
        "https://mangaupdates.com/series/pi4azuo"
    )
    with pytest.raises(ms.MetadataLinkError):
        ms.identity("https://example.com/series/1")


def test_the_same_metadata_link_cannot_be_used_twice(fastapi_app):
    link = f"https://www.anime-planet.com/manga/dup-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        manga = Manga(title="First", source_url=f"https://src.example/{uuid.uuid4().hex}", mangaupdates_url=link, type="manhwa")
        db.add(manga)
        db.commit()
        assert series_import.find_series_by_metadata_link(db, link + "/").id == manga.id
        user = User(email=f"u-{uuid.uuid4().hex}@example.com", is_active=True, role=UserRole.ADMIN, is_main_admin=True, provider="magic_link")
        db.add(user)
        db.commit()

        class Payload:
            mangaupdates_url = link
            base_url = None
            type = "manhwa"
            title = None

        with pytest.raises(ApiError) as exc:
            series_import.queue_series_import(db, user, f"https://other.example/{uuid.uuid4().hex}", Payload(), can_approve=True)
        assert "already belongs to" in str(exc.value.message)
