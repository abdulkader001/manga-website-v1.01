"""F-92: the library batch endpoint checks rights for the whole list at once.

The query count must not grow with the number of series, and the rights
rules must stay the same: a taken-down series is left out for readers and
kept for admins.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Manga, User, UserRole


def _seed(n: int, **fields) -> list[int]:
    ids = []
    with SessionLocal() as session:
        for _ in range(n):
            tag = uuid.uuid4().hex[:8]
            manga = Manga(title=f"B {tag}", slug=f"b-{tag}", source_url=f"https://lib.example/{tag}", **fields)
            session.add(manga)
            session.flush()
            ids.append(manga.id)
        session.commit()
    return ids


def _count_queries(client, path: str, headers=None) -> tuple[int, dict]:
    seen = {"n": 0}

    def before(*_a, **_k):
        seen["n"] += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        response = client.get(path, headers=headers or {})
    finally:
        event.remove(engine, "before_cursor_execute", before)
    assert response.status_code == 200, response.text
    return seen["n"], response.json()


def test_query_count_does_not_grow_with_the_list(fastapi_client):
    Base.metadata.create_all(bind=engine)
    few = _seed(3)
    many = _seed(30)
    small, _ = _count_queries(fastapi_client, "/api/v1/manga/batch?ids=" + ",".join(map(str, few)))
    large, body = _count_queries(fastapi_client, "/api/v1/manga/batch?ids=" + ",".join(map(str, many)))
    assert len(body["items"]) == 30
    assert large <= small + 2, (small, large)


def test_taken_down_hidden_from_readers_kept_for_admins(fastapi_client):
    Base.metadata.create_all(bind=engine)
    ok = _seed(1)
    down = _seed(1, takedown_status="taken_down")
    path = f"/api/v1/manga/batch?ids={ok[0]},{down[0]}"

    _, reader_view = _count_queries(fastapi_client, path)
    assert [item["id"] for item in reader_view["items"]] == ok

    with SessionLocal() as session:
        admin = User(
            email=f"lib-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Lib",
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        token = create_access_token(str(admin.id))
    _, admin_view = _count_queries(fastapi_client, path, {"Authorization": f"Bearer {token}"})
    assert sorted(item["id"] for item in admin_view["items"]) == sorted(ok + down)
