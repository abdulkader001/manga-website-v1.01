"""Stored chapter pictures keep the source's full quality.

The owner's report: scraped pictures looked poor. Every page used to be
re-encoded as lossy WebP and shrunk to 1440px wide. Now a source picture that
needs no change is stored byte for byte; only pictures that must change
(spread cut, strip slicing, too wide, transparency, other formats) are
re-encoded, at a higher quality and a 2000px cap.
"""

from __future__ import annotations

import io
import uuid

import pytest
import requests
from PIL import Image

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Manga
from backend_fastapi.app.services import page_image_service as pis


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch, fastapi_app):
    monkeypatch.setenv("PAGE_STORAGE_DIR", str(tmp_path / "pages"))
    monkeypatch.delenv("PAGE_KEEP_ORIGINALS", raising=False)
    monkeypatch.delenv("PAGE_MAX_WIDTH", raising=False)
    return tmp_path / "pages"


def _picture(fmt: str, size=(900, 1300), mode="RGB") -> bytes:
    image = Image.effect_noise(size, 50).convert(mode)
    out = io.BytesIO()
    image.save(out, fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    return out.getvalue()


def _serve(monkeypatch, mapping: dict, seen_headers: list | None = None):
    def fake_get(url, *args, **kwargs):
        if seen_headers is not None:
            seen_headers.append(kwargs.get("headers") or {})
        response = requests.Response()
        response.status_code = 200
        response._content = mapping[url]
        return response

    monkeypatch.setattr(
        "backend_fastapi.app.scrapers.http_client.RequestWrapper.get", staticmethod(fake_get)
    )


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")])
def test_a_page_that_needs_no_change_is_stored_byte_for_byte(fmt, ext):
    raw = _picture(fmt)
    [piece] = pis.compress_page(raw)
    assert piece.data == raw and piece.ext == ext
    assert (piece.width, piece.height) == (900, 1300)


def test_pages_that_must_change_are_still_reencoded():
    wide = _picture("JPEG", size=(2600, 1200))  # wider than the cap
    tall = _picture("JPEG", size=(800, 7000))  # webtoon strip: sliced
    transparent = _picture("PNG", mode="RGBA")
    gif = _picture("GIF")
    for raw in (wide, tall, transparent, gif):
        for piece in pis.compress_page(raw):
            assert piece.ext == "webp"
            assert Image.open(io.BytesIO(piece.data)).format == "WEBP"
            assert piece.width <= pis.max_width()


def test_the_switch_turns_reencoding_back_on(monkeypatch):
    monkeypatch.setenv("PAGE_KEEP_ORIGINALS", "false")
    [piece] = pis.compress_page(_picture("JPEG"))
    assert piece.ext == "webp"


def test_mirrored_originals_are_served_with_their_own_type(monkeypatch, fastapi_client):
    url = "https://s.example/keep.jpg"
    raw = _picture("JPEG")
    seen: list = []
    _serve(monkeypatch, {url: raw}, seen)
    # The picture route serves pages of a series that exists and may be hosted.
    with SessionLocal() as session:
        manga = Manga(title="Originals", source_url=f"https://s.example/{uuid.uuid4().hex}")
        session.add(manga)
        session.commit()
        manga_id = manga.id
    local = pis.mirror_chapter(manga_id, 210, [url]).urls[0]
    assert local.endswith(".jpg")
    response = fastapi_client.get(local)
    assert response.status_code == 200
    headers = {k.lower(): v for k, v in dict(response.headers).items()}
    assert headers["content-type"] == "image/jpeg"
    assert pis.path_from_url(local).read_bytes() == raw
    # Originals are asked for first, so image CDNs don't send a recompressed copy.
    assert seen[0]["Accept"].startswith("image/jpeg")
