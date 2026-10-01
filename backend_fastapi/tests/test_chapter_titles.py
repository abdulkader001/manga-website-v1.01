"""Readable, translated chapter titles."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga
from backend_fastapi.app.services import chapter_title_service as cts


@pytest.mark.parametrize(
    ("raw", "number", "expected"),
    [
        ("522 원준 522화 2024-11-07", 522, "원준"),
        ("제12화", 12, None),
        ("第12话 重逢", 12, "重逢"),
        ("Chapter 12: The Return", 12, "The Return"),
        ("Episode 5 - 2024.01.02", 5, None),
        ("Ch. 3.5", 3.5, None),
        ("A New Beginning", 7, "A New Beginning"),
        ("", 1, None),
    ],
)
def test_clean_title(raw, number, expected):
    assert cts.clean_title(raw, number) == expected


def _series(chapter_titles):
    with SessionLocal() as db:
        manga = Manga(
            title=f"Dragon Prince Yuan {uuid.uuid4().hex[:6]}",
            source_url=f"https://src.example/{uuid.uuid4().hex}",
            type="manhua",
        )
        db.add(manga)
        db.flush()
        for number, raw in chapter_titles:
            db.add(
                Chapter(
                    manga_id=manga.id,
                    chapter_number=number,
                    chapter_title=raw,
                    chapter_url=f"https://src.example/{uuid.uuid4().hex}",
                )
            )
        db.commit()
        return manga.id


def test_series_name_noise_is_dropped(fastapi_app):
    manga_id = _series([(n, f"{n} 원준 {n}화 2024-11-0{n % 9 + 1}") for n in range(520, 526)])
    with SessionLocal() as db:
        titles = cts.display_titles(db, db.get(Manga, manga_id), "en")
    assert {t["title"] for t in titles.values()} == {f"Chapter {n}" for n in range(520, 526)}
    assert all(t["original"] for t in titles.values())


def test_real_subtitles_are_translated_once_and_cached(fastapi_app):
    manga_id = _series(
        [(1, "1화 시작"), (2, "2화 재회"), (3, "3화 시작"), (4, "4화 결전"), (5, "5화 최종화 2024-01-01")]
    )
    calls = []
    words = {"시작": "Beginning", "재회": "Reunion", "결전": "Showdown"}

    def translate(text):
        calls.append(text)
        return words.get(text, text)  # echoes = "not translated"

    with SessionLocal() as db:
        manga = db.get(Manga, manga_id)
        titles = cts.display_titles(db, manga, "en", translate=translate)
    by_number = {t["title"].split(":")[0]: t["title"] for t in titles.values()}
    assert by_number["Chapter 1"] == "Chapter 1: Beginning"
    assert by_number["Chapter 3"] == "Chapter 3: Beginning"
    assert by_number["Chapter 4"] == "Chapter 4: Showdown"
    # "최종화" came back untranslated: the foreign text is not shown.
    assert by_number["Chapter 5"] == "Chapter 5"
    # One call per distinct subtitle, not per chapter.
    assert sorted(calls) == sorted({"시작", "재회", "결전", "최종화"})

    calls.clear()
    with SessionLocal() as db:
        titles = cts.display_titles(db, db.get(Manga, manga_id), "en", translate=translate)
    assert calls == ["최종화"]  # cached ones are not asked again
    assert "Chapter 2: Reunion" in {t["title"] for t in titles.values()}


def test_chapter_titles_endpoint(fastapi_client):
    manga_id = _series([(n, f"{n} 원준 {n}화") for n in range(1, 5)])
    resp = fastapi_client.get(f"/api/v1/manga/{manga_id}/chapter-titles?lang=en")
    assert resp.status_code == 200, resp.text
    assert {v["title"] for v in resp.json()["titles"].values()} == {f"Chapter {n}" for n in range(1, 5)}
