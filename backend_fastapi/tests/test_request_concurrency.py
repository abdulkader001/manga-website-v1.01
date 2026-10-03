"""The API must not freeze when many readers arrive at once.

Before: the sign-in, "sign-in required" and permission guards were
``async def`` and queried the database on the event loop, and each request
kept two to four pooled connections. A burst emptied the pool, the event loop
waited for a connection, nothing could hand one back, and the worker stopped
answering (12 concurrent requests froze it with the small-server pool of 4+4).
"""

from __future__ import annotations

import ast
import inspect
import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Chapter, Manga, User

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def test_database_guards_run_in_the_thread_pool():
    from backend_fastapi.app.dependencies import auth, site_access
    from backend_fastapi.app.dependencies.site_functions import require_function

    for guard in (
        auth.get_current_user,
        auth.get_optional_user,
        auth.require_permission("view_system_health"),
        site_access.require_site_access,
        require_function("comments"),
    ):
        assert not inspect.iscoroutinefunction(guard), guard.__name__


def test_no_async_dependency_touches_the_database():
    # Any ``async def`` used in Depends(...) runs on the event loop: a
    # database call inside it stalls every request of the worker.
    async_defs: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    for path in APP.rglob("*.py"):
        source = path.read_text()
        used |= set(re.findall(r"Depends\(\s*([A-Za-z_]\w*)", source))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.AsyncFunctionDef):
                async_defs[node.name] = (str(path), ast.get_source_segment(source, node) or "")
    offenders = [
        f"{name} ({where})"
        for name, (where, body) in async_defs.items()
        if name in used and re.search(r"\b(db|Session|SessionLocal)\b", body)
    ]
    assert offenders == []


def test_the_user_lookup_gives_its_connection_back():
    from backend_fastapi.app.dependencies.auth import _resolve_user

    with SessionLocal() as session:
        user = User(email=f"r-{uuid.uuid4().hex}@example.com", is_active=True, name="Reader", provider="magic_link")
        session.add(user)
        session.commit()
        token = create_access_token(str(user.id))

    with SessionLocal() as db:
        found = _resolve_user(token, db, allow_anonymous=True)
        assert found is not None and found.name == "Reader"
        # No open transaction means no pooled connection held while the
        # route runs.
        assert not db.in_transaction()


def test_an_empty_pool_answers_busy_not_sign_in(fastapi_client, monkeypatch):
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from backend_fastapi.app.dependencies import site_access

    class Busy:
        def query(self, *_a, **_k):
            raise PoolTimeout("QueuePool limit of size 4 overflow 4 reached")

        def rollback(self):
            pass

    with pytest.raises(PoolTimeout):
        site_access.login_required(Busy())

    def busy(_db):
        raise PoolTimeout("QueuePool limit of size 4 overflow 4 reached")

    monkeypatch.setattr(site_access, "login_required", busy)
    resp = fastapi_client.get("/api/v1/manga/")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    headers = {k.lower(): v for k, v in dict(resp.headers).items()}  # the httpx stub may give pairs
    assert headers.get("retry-after") == "2"


def test_previous_and_next_follow_chapter_order(fastapi_client):
    with SessionLocal() as session:
        manga = Manga(title="Order", source_url=f"https://src.example/{uuid.uuid4().hex}")
        session.add(manga)
        session.flush()
        ids = []
        for number in (2, 0, 1, 1):
            chapter = Chapter(
                manga_id=manga.id,
                chapter_number=number,
                chapter_url=f"https://src.example/c/{uuid.uuid4().hex}",
                pages=[],
                created_at=datetime.utcnow(),
            )
            session.add(chapter)
            session.flush()
            ids.append(chapter.id)
        session.commit()
        manga_id = manga.id
    two, zero, one_a, one_b = ids
    order = [zero, one_a, one_b, two]

    for i, chapter_id in enumerate(order):
        body = fastapi_client.get(f"/api/v1/manga/{manga_id}/chapters/{chapter_id}").json()
        assert body["prev_chapter_id"] == (order[i - 1] if i > 0 else None)
        assert body["next_chapter_id"] == (order[i + 1] if i < len(order) - 1 else None)
