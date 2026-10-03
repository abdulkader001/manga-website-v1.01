"""Chapter pictures do not use up the reader's API allowance.

The owner's report: reading a freshly scraped chapter ended in "Chapter Load
Error -- Too many requests". Each page picture of a chapter not mirrored yet
is one ``/api/v1/images/proxy`` request, so one long chapter spent the whole
300-a-minute budget and the next API call was refused.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend_fastapi.app.utils.rate_limiter import IMAGE_LIMIT_MULTIPLIER, IMAGE_PATH_RE, RateLimitMiddleware


def _client(limit: int = 3) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=limit, window_seconds=60)

    @app.get("/api/v1/images/proxy")
    def proxy():
        return {"ok": True}

    @app.get("/api/v1/manga/pages/{m}/{c}/{f}")
    def page(m: int, c: int, f: str):
        return {"ok": True}

    @app.get("/api/v1/manga/{m}/chapters/{c}")
    def chapter(m: int, c: int):
        return {"ok": True}

    return TestClient(app)


def test_picture_paths_are_recognised():
    assert IMAGE_PATH_RE.match("/api/v1/images/proxy")
    assert IMAGE_PATH_RE.match("/api/images/proxy")
    assert IMAGE_PATH_RE.match("/api/v1/manga/pages/1/2/001.webp")
    assert IMAGE_PATH_RE.match("/api/v1/manga/covers/x.webp")
    assert not IMAGE_PATH_RE.match("/api/v1/manga/1/chapters/2")
    assert not IMAGE_PATH_RE.match("/api/v1/images/proxy/extra")


def test_many_pictures_leave_the_chapter_call_working():
    client = _client(limit=3)
    for n in range(3 * IMAGE_LIMIT_MULTIPLIER):
        assert client.get("/api/v1/images/proxy").status_code == 200, n
    assert client.get("/api/v1/manga/1/chapters/2").status_code == 200


def test_pictures_still_have_a_ceiling():
    client = _client(limit=2)
    codes = [client.get("/api/v1/manga/pages/1/2/a.webp").status_code for _ in range(2 * IMAGE_LIMIT_MULTIPLIER + 1)]
    assert codes[-1] == 429
    assert codes.count(200) == 2 * IMAGE_LIMIT_MULTIPLIER


def test_api_calls_keep_the_normal_limit():
    client = _client(limit=2)
    codes = [client.get("/api/v1/manga/1/chapters/2").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
