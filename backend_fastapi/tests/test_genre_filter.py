"""Regression tests for indexed genre filtering (H3 / item 9)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Manga
from backend_fastapi.app.services.manga_service import (
    apply_genre_filters,
    get_manga_list,
)
from _support.db_reset import clear_content


class _Q:
    """Minimal query shim so we can compile apply_genre_filters output."""

    def __init__(self, stmt):
        self.stmt = stmt

    def filter(self, *criteria):
        return _Q(self.stmt.where(*criteria))


def _compile(dialect_name, dialect):
    stmt = apply_genre_filters(
        _Q(select(Manga.id)), ["action"], ["horror"], dialect_name=dialect_name
    ).stmt
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_postgres_genre_filter_uses_indexable_jsonb_operator():
    sql = _compile("postgresql", postgresql.dialect())
    # JSONB existence operator (?) is usable by the ix_manga_genres_gin index;
    # the old cast-to-TEXT LIKE could never use an index.
    assert "JSONB" in sql
    assert "?" in sql
    assert "LIKE" not in sql.upper()


def test_sqlite_genre_filter_falls_back_to_text_match():
    sql = _compile("sqlite", sqlite.dialect())
    assert "LIKE" in sql.upper()


def test_genre_include_exclude_behaviour(fastapi_app):
    session = SessionLocal()
    try:
        clear_content(session, commit=False)
        session.commit()
        session.add_all(
            [
                Manga(
                    title="A",
                    source_url="https://x/a",
                    genres=["action", "comedy"],
                ),
                Manga(
                    title="B",
                    source_url="https://x/b",
                    genres=["horror"],
                ),
                Manga(
                    title="C",
                    source_url="https://x/c",
                    genres=["action", "horror"],
                ),
            ]
        )
        session.commit()

        # include action -> A and C
        items, total, _ = get_manga_list(
            session, None, None, None, ["action"], [], "new", 1, 20
        )
        assert total == 2
        assert {m.title for m in items} == {"A", "C"}

        # include action, exclude horror -> only A
        items, total, _ = get_manga_list(
            session, None, None, None, ["action"], ["horror"], "new", 1, 20
        )
        assert total == 1
        assert {m.title for m in items} == {"A"}

        # case-insensitive include
        items, total, _ = get_manga_list(
            session, None, None, None, ["ACTION"], [], "new", 1, 20
        )
        assert total == 2
    finally:
        session.close()


def test_manga_title_index_declared_on_model():
    index_names = {ix.name for ix in Manga.__table__.indexes}
    assert "ix_manga_title" in index_names
