"""Regression tests for F-65 — ``users.created_at`` must never be NULL.

Background
----------
``User.created_at`` was declared with ``server_default=func.now()`` only. That
default exists in the *model*, but the migration chain never created it on the
real column, so on PostgreSQL every row inserted without an explicit value got
``created_at = NULL``. ``UserRead.created_at`` is a non-optional ``datetime``,
so ``GET /auth/me`` then raised ``ResponseValidationError`` -> 500 for that user
forever, and ``AuthContext`` cannot distinguish a 500 from a logout, leaving new
accounts in an unbreakable login loop.

Why the existing suite never caught it
--------------------------------------
``conftest.py`` builds the test database with ``Base.metadata.create_all`` on
SQLite, which *does* emit the model's ``server_default``. Any test that simply
creates a user and reads it back is therefore green against the broken code and
proves nothing. The tests below are written specifically to be independent of
whatever DDL the harness happens to produce:

* ``test_created_at_has_python_side_default`` asserts the application populates
  the column itself rather than delegating to the database. This is the actual
  defect — reliance on DDL that production did not have.
* ``test_created_at_populated_when_database_has_no_default`` rebuilds the table
  with every default stripped, which is what production's schema really looked
  like, and drives the real signup helper against it.

Both fail against the pre-fix code and pass after it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.orm import sessionmaker

from backend_fastapi.app.models import User


def test_created_at_has_python_side_default() -> None:
    """The app must set ``created_at`` itself, not rely on database DDL.

    Pre-fix this is ``None`` — the column carried only a ``server_default``,
    which the production migration chain never actually created.
    """

    column = User.__table__.c.created_at

    assert column.default is not None, (
        "users.created_at has no Python-side default, so the application "
        "depends on the database carrying one. Production's migrated column "
        "does not, which is exactly how every new user got created_at=NULL."
    )


def test_created_at_is_not_nullable() -> None:
    """``created_at`` must be NOT NULL so a NULL can never reappear."""

    assert User.__table__.c.created_at.nullable is False, (
        "users.created_at is nullable; a NULL here 500s GET /auth/me forever "
        "because UserRead.created_at is a required datetime."
    )


def test_created_at_populated_when_database_has_no_default() -> None:
    """Reproduce production's schema — no column default — and sign a user up.

    This is the decisive test. It rebuilds ``users`` with every server-side
    default removed, which is what the migrated PostgreSQL table really looked
    like, then inserts through the ORM exactly as ``ensure_magic_link_user``
    does. Pre-fix the row comes back with ``created_at = None``.
    """

    stripped = MetaData()
    source = User.__table__

    columns = []
    for col in source.columns:
        copied = col._copy()
        if col.name == "created_at":
            # Reproduce the real production column, and *only* that column:
            # no DDL-level default, and nullable, so a broken insert records
            # NULL rather than raising. Every other column keeps its defaults
            # so this test fails for exactly one reason.
            copied.server_default = None
            copied.server_onupdate = None
            copied.nullable = True
        columns.append(copied)

    Table("users", stripped, *columns)

    engine = create_engine("sqlite://")
    stripped.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        user = User(email="f65-regression@example.com", username="f65")
        session.add(user)
        session.commit()
        session.refresh(user)

        assert user.created_at is not None, (
            "A user created against a database with no column default got "
            "created_at=NULL. GET /auth/me returns 500 for this user forever."
        )


@pytest.mark.infrastructure
def test_migrated_column_has_a_database_default() -> None:
    """The migrated PostgreSQL column must carry its own default.

    This is the production defect stated directly. The SQLite harness cannot
    express it — ``create_all`` emits the model's ``server_default``, so the
    bug is invisible there — which is why this test is marked ``infrastructure``
    and asserts against a real migrated database instead.

    Pre-fix, ``users.created_at`` had no ``column_default`` while its sibling
    ``updated_at`` had ``now()``.
    """

    import os

    database_url = os.getenv("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite"):
        pytest.skip("requires a real migrated PostgreSQL database")

    engine = create_engine(database_url)
    with engine.connect() as conn:
        from sqlalchemy import text

        default = conn.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'created_at'"
            )
        ).scalar()

        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'created_at'"
            )
        ).scalar()

    assert default is not None, (
        "The migrated users.created_at column has no DEFAULT. Every user "
        "inserted without an explicit value gets NULL, and GET /auth/me then "
        "returns 500 for that user forever."
    )
    assert nullable == "NO", (
        "The migrated users.created_at column is still nullable, so a NULL "
        "can reappear and re-break GET /auth/me."
    )
