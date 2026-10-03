"""Chapter page mirroring: compression to one lightweight WebP format,
slicing of tall strips, safe storage, fallback to the source, serving."""

from __future__ import annotations

import io
import uuid

import pytest
import requests
from PIL import Image, ImageDraw

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga
from backend_fastapi.app.services import image_proxy, page_image_service as pis, page_mirror_service
from backend_fastapi.app.services.region_classifier import sample_background
from backend_fastapi.app.utils.image_safety import InvalidImageError


def _png(size=(2000, 2600), fill="white", strokes=True) -> bytes:
    image = Image.new("RGB", size, fill)
    if strokes:
        draw = ImageDraw.Draw(image)
        for i in range(60):
            draw.rectangle([i * 20, i * 30, i * 20 + 150, i * 30 + 12], fill="black")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _jpeg(size=(1800, 2400)) -> bytes:
    import random

    random.seed(1)
    image = Image.effect_noise(size, 60).convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch, fastapi_app):
    monkeypatch.setenv("PAGE_STORAGE_DIR", str(tmp_path / "pages"))
    # These tests cover the re-encoding path; keeping untouched source files
    # (the default) is covered in test_page_originals.py.
    monkeypatch.setenv("PAGE_KEEP_ORIGINALS", "false")
    return tmp_path / "pages"


def _serve(monkeypatch, mapping: dict):
    """Answer RequestWrapper.get from ``mapping`` (url -> bytes | Exception)."""

    def fake_get(url, *args, **kwargs):
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        response = requests.Response()
        response.status_code = 200
        response._content = value
        return response

    monkeypatch.setattr(
        "backend_fastapi.app.scrapers.http_client.RequestWrapper.get", staticmethod(fake_get)
    )


# ------------------------------------------------------------------ compression
def test_every_source_format_becomes_webp_capped_in_width():
    for raw in (_png(), _jpeg()):
        pieces = pis.compress_page(raw)
        assert pieces
        for piece in pieces:
            image = Image.open(io.BytesIO(piece.data))
            assert image.format == "WEBP"
            assert piece.width <= pis.max_width() and image.width == piece.width


def test_a_photographic_jpeg_gets_much_smaller():
    raw = _jpeg()
    assert sum(len(p.data) for p in pis.compress_page(raw)) < len(raw)


def test_tall_strips_are_sliced_without_losing_or_duplicating_pixels():
    strip = Image.new("RGB", (900, 14000), "white")
    draw = ImageDraw.Draw(strip)
    for top in range(0, 14000, 900):
        draw.rectangle([100, top + 100, 800, top + 700], fill=(30, 60, 200))
    out = io.BytesIO()
    strip.save(out, "PNG")
    pieces = pis.compress_page(out.getvalue())
    assert len(pieces) >= 5
    assert all(p.height <= pis.MAX_SLICE_HEIGHT for p in pieces)
    assert sum(p.height for p in pieces) == 14000


def test_transparent_images_are_flattened_onto_white():
    rgba = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    out = io.BytesIO()
    rgba.save(out, "PNG")
    piece = pis.compress_page(out.getvalue())[0]
    pixel = Image.open(io.BytesIO(piece.data)).convert("RGB").getpixel((10, 10))
    assert min(pixel) >= 250


def test_non_images_are_rejected():
    with pytest.raises(InvalidImageError):
        pis.compress_page(b"<html>blocked</html>")


# ------------------------------------------------------------------ storage safety
def test_only_names_this_service_wrote_resolve_to_files():
    assert pis.path_for(1, 2, "../../etc/passwd") is None
    assert pis.path_for(1, 2, "0001-abcdef0123.png") is None
    assert pis.path_from_url("/api/v1/manga/pages/1/2/../../x") is None
    assert pis.path_from_url("https://elsewhere.example/a.jpg") is None


# ------------------------------------------------------------------ mirroring
def test_failed_pages_keep_their_source_url_and_order_is_preserved(monkeypatch):
    good, bad, junk = "https://s.example/1.png", "https://s.example/2.png", "https://s.example/3.png"
    _serve(monkeypatch, {good: _png(), bad: requests.ConnectionError("down"), junk: b"not an image"})
    result = pis.mirror_chapter(7, 70, [good, bad, junk])
    assert result.mirrored and result.failed == 2
    assert pis.is_local_url(result.urls[0])
    assert result.urls[1:] == [bad, junk]
    assert pis.path_from_url(result.urls[0]).read_bytes()[:4] == b"RIFF"
    assert result.stored_bytes > 0


def test_nothing_is_stored_when_every_page_fails(monkeypatch, storage):
    url = "https://s.example/1.png"
    _serve(monkeypatch, {url: requests.ConnectionError("down")})
    result = pis.mirror_chapter(7, 71, [url])
    assert not result.mirrored and result.urls == [url]
    assert not (storage / "7" / "71").exists()
    assert not [p for p in (storage / "7").glob("*")] if (storage / "7").exists() else True


def test_remirroring_replaces_the_previous_files(monkeypatch, storage):
    url = "https://s.example/1.png"
    _serve(monkeypatch, {url: _png(fill="white")})
    first = pis.mirror_chapter(8, 80, [url]).urls
    _serve(monkeypatch, {url: _png(fill="#eeeeee")})
    second = pis.mirror_chapter(8, 80, [url]).urls
    assert first != second
    assert len(list((storage / "8" / "80").glob("*.webp"))) == 1


def _chapter(pages) -> tuple[int, int]:
    session = SessionLocal()
    try:
        manga = Manga(title=f"Mirror {uuid.uuid4().hex[:6]}", source_url=f"https://m.example/{uuid.uuid4().hex}")
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://m.example/{uuid.uuid4().hex}/ch-1",
            pages=pages,
        )
        session.add(chapter)
        session.commit()
        return manga.id, chapter.id
    finally:
        session.close()


def test_mirroring_a_chapter_swaps_pages_and_keeps_the_sources(monkeypatch):
    urls = [f"https://s.example/{uuid.uuid4().hex}.png" for _ in range(2)]
    _serve(monkeypatch, {u: _png() for u in urls})
    _, chapter_id = _chapter(urls)
    session = SessionLocal()
    try:
        outcome = page_mirror_service.mirror_chapter_by_id(session, chapter_id)
        chapter = session.get(Chapter, chapter_id)
        assert outcome["status"] == "success"
        assert all(pis.is_local_url(p) for p in chapter.pages)
        assert chapter.source_pages == urls
        assert chapter.pages_bytes and chapter.pages_bytes > 0
        # nothing left to do
        assert page_mirror_service.mirror_chapter_by_id(session, chapter_id)["status"] == "skipped"
    finally:
        session.close()


def test_a_chapter_whose_pages_all_fail_stays_readable_from_the_source(monkeypatch):
    urls = ["https://s.example/dead1.png", "https://s.example/dead2.png"]
    _serve(monkeypatch, {u: requests.ConnectionError("down") for u in urls})
    _, chapter_id = _chapter(urls)
    session = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            page_mirror_service.mirror_chapter_by_id(session, chapter_id)
        assert session.get(Chapter, chapter_id).pages == urls
    finally:
        session.close()


def test_mirroring_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MIRROR_PAGE_IMAGES", "false")
    _, chapter_id = _chapter(["https://s.example/x.png"])
    session = SessionLocal()
    try:
        assert page_mirror_service.mirror_chapter_by_id(session, chapter_id)["reason"] == "disabled"
    finally:
        session.close()


# ------------------------------------------------------------------ serving and reading
def test_stored_pages_are_served_as_immutable_webp(monkeypatch, fastapi_client):
    url = "https://s.example/serve.png"
    _serve(monkeypatch, {url: _png()})
    # The picture route serves pages of a series that exists and may be hosted.
    with SessionLocal() as session:
        manga = Manga(title="Served", source_url=f"https://s.example/{uuid.uuid4().hex}")
        session.add(manga)
        session.commit()
        manga_id = manga.id
    local = pis.mirror_chapter(manga_id, 90, [url]).urls[0]
    response = fastapi_client.get(local)
    assert response.status_code == 200
    headers = {k.lower(): v for k, v in dict(response.headers).items()}
    assert headers["content-type"] == "image/webp"
    assert "immutable" in headers["cache-control"]
    assert fastapi_client.get(local.rsplit("/", 1)[0] + "/9999-abcdef0123.webp").status_code == 404
    assert fastapi_client.get(local.rsplit("/", 1)[0] + "/..%2F..%2Fsecret").status_code in (404, 422)


def test_reader_urls_use_our_copies_directly_and_proxy_only_source_urls(monkeypatch):
    url = "https://s.example/read.png"
    _serve(monkeypatch, {url: _png()})
    local = pis.mirror_chapter(10, 100, [url]).urls[0]
    session = SessionLocal()
    try:
        chapter = Chapter(manga_id=10, chapter_number=1, chapter_url="https://s.example/c", pages=[local])
        assert image_proxy.reader_page_urls(session, chapter) == [local]
    finally:
        session.close()


def test_processing_reads_our_copies_from_disk_not_the_network(monkeypatch):
    from backend_fastapi.app.api.routers import processing

    url = "https://s.example/ocr.png"
    _serve(monkeypatch, {url: _png()})
    local = pis.mirror_chapter(11, 110, [url]).urls[0]
    data = processing._fetch_image_bytes_sync(local)
    assert Image.open(io.BytesIO(data)).format == "WEBP"


# ------------------------------------------------------------------ erasing text under the translation
def test_bubble_fill_is_sampled_so_the_translation_can_replace_the_text():
    page = Image.new("RGB", (600, 400), (240, 230, 200))
    draw = ImageDraw.Draw(page)
    draw.rectangle([200, 150, 400, 200], fill="black")  # the "lettering"
    styling = sample_background(page, {"x": 200, "y": 150, "width": 200, "height": 50})
    assert styling["background"] == "#f0e6c8"
    assert styling["text_color"] == "#111111"
    assert styling["background_clean"] is True


def test_busy_artwork_is_flagged_so_no_solid_patch_is_drawn():
    import random

    random.seed(2)
    page = Image.new("RGB", (400, 300))
    page.putdata([(random.randint(0, 255),) * 3 for _ in range(400 * 300)])
    styling = sample_background(page, {"x": 100, "y": 100, "width": 150, "height": 60})
    assert styling["background_clean"] is False
