"""Update cards show when the newest chapter arrived, in true UTC order."""

from __future__ import annotations

import datetime as dt
import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga


def _series(title, *, added_hours_ago, chapter_hours_ago):
    now = dt.datetime.utcnow()
    with SessionLocal() as s:
        m = Manga(
            title=title, type="manhwa", status="ongoing",
            source_url=f"https://x.example/{uuid.uuid4().hex}",
        )
        m.created_at = now - dt.timedelta(hours=added_hours_ago)
        s.add(m)
        s.commit()
        for n, hours in enumerate(chapter_hours_ago, start=1):
            s.add(Chapter(
                manga_id=m.id, chapter_number=n,
                chapter_url=f"https://x.example/{uuid.uuid4().hex}",
                created_at=now - dt.timedelta(hours=hours),
            ))
        s.commit()
        return m.id


def test_cards_carry_the_newest_chapter_time_and_latest_orders_by_it(fastapi_client):
    old_series_new_chapter = _series("Old series", added_hours_ago=48, chapter_hours_ago=[40, 1])
    new_series_old_chapters = _series("New series", added_hours_ago=3, chapter_hours_ago=[3, 3])

    items = fastapi_client.get("/api/v1/manga/", params={"sort": "latest", "per_page": 100}).json()["items"]
    by_id = {i["id"]: i for i in items}
    order = [i["id"] for i in items if i["id"] in (old_series_new_chapter, new_series_old_chapters)]
    # A fresh chapter puts the old series first.
    assert order == [old_series_new_chapter, new_series_old_chapters]

    stamp = by_id[old_series_new_chapter]["last_chapter_at"]
    assert stamp.endswith("Z")
    age = dt.datetime.utcnow() - dt.datetime.fromisoformat(stamp[:-1])
    assert dt.timedelta(minutes=55) < age < dt.timedelta(minutes=65)

    chapters = fastapi_client.get(f"/api/v1/manga/{new_series_old_chapters}/chapters").json()
    assert all(c["created_at"].endswith("Z") for c in chapters)
