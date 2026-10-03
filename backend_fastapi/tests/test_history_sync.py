"""A signed-in reader's read chapters follow them to a new device.

The browser stays the main copy; for a signed-in reader the server also keeps
which chapters were opened and when (``read_history``), so the dimmed chapters
and "where I stopped" appear on a phone they just signed in on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Chapter, Manga, ReadHistory, User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _headers() -> tuple[dict[str, str], int]:
    with SessionLocal() as session:
        user = User(
            email=f"hist-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Reader",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}, user_id


def _series(chapters: int = 3) -> tuple[int, list[int]]:
    with SessionLocal() as session:
        manga = Manga(
            title=f"History Series {uuid.uuid4().hex[:6]}",
            source_url=f"https://example.com/h/{uuid.uuid4().hex[:8]}",
        )
        session.add(manga)
        session.flush()
        ids = []
        for number in range(1, chapters + 1):
            chapter = Chapter(
                manga_id=manga.id,
                chapter_number=number,
                chapter_title=f"Ch {number}",
                chapter_url=f"https://example.com/h/{manga.id}/{number}",
            )
            session.add(chapter)
            session.flush()
            ids.append(chapter.id)
        session.commit()
        return manga.id, ids


def _sync(client, headers, **body):
    return client.post("/api/history/sync", json=body, headers=headers)


def _rows(user_id: int) -> list[ReadHistory]:
    with SessionLocal() as session:
        return session.query(ReadHistory).filter(ReadHistory.user_id == user_id).all()


def test_a_new_device_gets_the_chapters_read_on_the_old_one(fastapi_client):
    headers, _ = _headers()
    manga_id, chapters = _series()

    up = _sync(
        fastapi_client,
        headers,
        entries=[
            {"chapter_id": chapters[0], "read_at": "2026-01-01T10:00:00Z"},
            {"chapter_id": chapters[1], "read_at": "2026-01-02T10:00:00Z"},
        ],
    )
    assert up.status_code == 200, up.text

    # The phone has nothing of its own: it asks and receives both.
    phone = _sync(fastapi_client, headers)
    entries = phone.json()["entries"]
    assert {e["chapter_id"] for e in entries} == {chapters[0], chapters[1]}
    assert {e["manga_id"] for e in entries} == {manga_id}
    newest = entries[0]
    assert newest["chapter_id"] == chapters[1] and newest["chapter_number"] == 2


def test_sending_the_same_chapters_again_adds_no_rows(fastapi_client):
    headers, user_id = _headers()
    _, chapters = _series()
    body = {"entries": [{"chapter_id": c} for c in chapters]}

    _sync(fastapi_client, headers, **body)
    _sync(fastapi_client, headers, **body)

    assert len(_rows(user_id)) == len(chapters)


def test_unknown_chapters_are_ignored(fastapi_client):
    headers, user_id = _headers()
    _, chapters = _series(1)

    response = _sync(
        fastapi_client, headers, entries=[{"chapter_id": 987654321}, {"chapter_id": chapters[0]}]
    )

    assert response.status_code == 200
    assert [e["chapter_id"] for e in response.json()["entries"]] == [chapters[0]]
    assert len(_rows(user_id)) == 1


def test_an_older_time_never_replaces_a_newer_one_and_the_future_is_clamped(fastapi_client):
    headers, user_id = _headers()
    _, chapters = _series(2)
    _sync(fastapi_client, headers, entries=[{"chapter_id": chapters[0], "read_at": "2026-03-01T00:00:00Z"}])
    _sync(fastapi_client, headers, entries=[{"chapter_id": chapters[0], "read_at": "2025-01-01T00:00:00Z"}])
    future = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    _sync(fastapi_client, headers, entries=[{"chapter_id": chapters[1], "read_at": future}])
    _sync(fastapi_client, headers, entries=[{"chapter_id": chapters[1], "read_at": "not a date"}])

    by_chapter = {r.chapter_id: r.last_read_at for r in _rows(user_id)}
    assert by_chapter[chapters[0]] == datetime(2026, 3, 1)
    assert by_chapter[chapters[1]] <= datetime.utcnow()


def test_opening_one_chapter_records_it(fastapi_client):
    headers, user_id = _headers()
    _, chapters = _series(1)

    response = fastapi_client.post("/api/history/read", json={"chapter_id": chapters[0]}, headers=headers)

    assert response.status_code == 200
    assert [r.chapter_id for r in _rows(user_id)] == [chapters[0]]


def test_clearing_one_series_or_everything(fastapi_client):
    headers, user_id = _headers()
    first_manga, first = _series(2)
    _, second = _series(1)
    _sync(fastapi_client, headers, entries=[{"chapter_id": c} for c in first + second])

    after_one = _sync(fastapi_client, headers, clear_manga=[first_manga])
    assert [e["chapter_id"] for e in after_one.json()["entries"]] == second

    after_all = _sync(fastapi_client, headers, clear_all=True)
    assert after_all.json()["entries"] == []
    assert _rows(user_id) == []


def test_a_clear_comes_before_the_chapters_sent_with_it(fastapi_client):
    headers, _ = _headers()
    manga_id, chapters = _series(2)
    _sync(fastapi_client, headers, entries=[{"chapter_id": chapters[0]}])

    # Cleared on the phone, then one chapter read: only that one remains.
    response = _sync(
        fastapi_client, headers, clear_manga=[manga_id], entries=[{"chapter_id": chapters[1]}]
    )

    assert [e["chapter_id"] for e in response.json()["entries"]] == [chapters[1]]


def test_one_reader_never_sees_anothers_chapters(fastapi_client):
    alice, _ = _headers()
    bob, _ = _headers()
    _, chapters = _series(1)
    _sync(fastapi_client, alice, entries=[{"chapter_id": chapters[0]}])

    assert _sync(fastapi_client, bob).json()["entries"] == []
    _sync(fastapi_client, bob, clear_all=True)
    assert len(_sync(fastapi_client, alice).json()["entries"]) == 1


def test_a_guest_cannot_use_it(fastapi_client):
    assert fastapi_client.post("/api/history/sync", json={}).status_code == 401
    assert fastapi_client.post("/api/history/read", json={"chapter_id": 1}).status_code == 401


def test_too_many_chapters_in_one_request_are_refused(fastapi_client):
    headers, _ = _headers()
    entries = [{"chapter_id": i} for i in range(1, 2002)]

    assert _sync(fastapi_client, headers, entries=entries).status_code == 422
