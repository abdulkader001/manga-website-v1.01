"""FK-safe table cleanup shared by every test that wipes users or content.

A dozen test modules opened with ``session.query(User).delete()``. That is
only valid on SQLite, which does not enforce foreign keys by default: against
PostgreSQL -- the engine production actually runs -- it raises
``ForeignKeyViolation`` from ``bookmarks``, ``notifications``, ``read_history``
and every other child table. It is the single reason the suite could not be
run against Postgres, and therefore the reason a Postgres-only defect (an
unauthenticated 500 from a bigint OFFSET overflow) shipped with 663 tests green.

The delete order is derived from the SQLAlchemy metadata rather than
hand-maintained, so a new model with a FK to ``users`` is handled without
anyone remembering to add a line here.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

# Never cleared: alembic bookkeeping, and the audit log, whose append-only
# trigger refuses DELETE by design (its user_id FK is ON DELETE SET NULL, so
# removing a user does not require clearing it).
PRESERVED_TABLES = frozenset({"alembic_version", "admin_audit_logs"})


def tables_to_clear(*root_names: str) -> list:
    """``root_names`` plus everything FK-dependent on them, children first."""

    from backend_fastapi.app.core.db import Base

    metadata = Base.metadata
    selected = {metadata.tables[name] for name in root_names if name in metadata.tables}

    changed = True
    while changed:
        changed = False
        for table in metadata.sorted_tables:
            if table in selected:
                continue
            if any(fk.column.table in selected for fk in table.foreign_keys):
                selected.add(table)
                changed = True

    # sorted_tables is parents-first; reverse it so children are deleted first.
    return [
        table
        for table in reversed(metadata.sorted_tables)
        if table in selected and table.name not in PRESERVED_TABLES
    ]


def clear_tables(session: Session, *root_names: str, commit: bool = True) -> None:
    """Delete ``root_names`` and their dependents in a FK-safe order."""

    for table in tables_to_clear(*root_names):
        session.execute(table.delete())
    if commit:
        session.commit()


def clear_users(session: Session, *, commit: bool = True) -> None:
    """Drop every user row along with everything that references one."""

    clear_tables(session, "users", commit=commit)


def clear_users_and_content(session: Session, *, commit: bool = True) -> None:
    """Drop users, manga and chapters along with everything referencing them."""

    clear_tables(session, "users", "manga", "chapters", commit=commit)


def clear_content(session: Session, *, commit: bool = True) -> None:
    """Drop manga and chapters along with everything that references them."""

    clear_tables(session, "manga", "chapters", commit=commit)


def clear_list_cache() -> None:
    """Drop cached catalogue pages from Redis (when the tests run with one).

    A list cached by an earlier test outlives its rows, so a test that seeds a
    series and reads the list would see the old page.
    """

    import os

    url = os.getenv("REDIS_URL")
    if not url:
        return
    import redis

    from backend_fastapi.app.utils import cache_invalidation

    client = redis.Redis.from_url(url)
    try:
        cache_invalidation.invalidate_manga_list_cache(client)
        cache_invalidation.invalidate_manga_detail_cache(client)
    finally:
        client.close()
