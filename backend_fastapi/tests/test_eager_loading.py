"""Regression tests for lazy-loading strategy (H2 / item 8).

Blanket ``lazy="selectin"`` on hot-path models caused over-fetching: every
``db.get(User, id)`` in the auth path and every ``GET /manga`` row eagerly
loaded unrelated collections. These assert the audit-named relationships load
lazily (``select``) so they are only fetched when actually accessed.
"""

from __future__ import annotations

from sqlalchemy import inspect

from backend_fastapi.app.models.manga import Manga
from backend_fastapi.app.models.user import User

USER_LAZY_SELECT_RELATIONSHIPS = {
    "read_history",
    "bookmarks",
    "complaints",
    "audit_logs",
    "api_keys",
    "custom_tabs",
    "comments",
    "issued_promotion_tokens",
    "assigned_promotion_tokens",
    "redeemed_promotion_tokens",
}

MANGA_LAZY_SELECT_RELATIONSHIPS = {
    "chapters",
    "scraping_jobs",
    "bookmarks",
    "read_history_entries",
}


def _lazy_strategy(model, name: str) -> str:
    return inspect(model).relationships[name].lazy


def test_user_collections_are_lazy_select():
    for name in USER_LAZY_SELECT_RELATIONSHIPS:
        assert _lazy_strategy(User, name) == "select", name


def test_manga_collections_are_lazy_select():
    for name in MANGA_LAZY_SELECT_RELATIONSHIPS:
        assert _lazy_strategy(Manga, name) == "select", name
