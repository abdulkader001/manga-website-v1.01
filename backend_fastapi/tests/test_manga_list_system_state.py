"""Regression tests for F-63 — the manga listing must not write on a read path.

Background
----------
``GET /api/v1/manga/`` and ``/manga/browse`` returned a flat 5.00s 504 on 100%
of requests whenever the ``system_state`` singleton row was absent — which is
every freshly migrated deployment, because nothing in the application creates
it (``ensure_system_state_initialized`` has no caller and no migration seeds
the row).

The cause was a single request opening two database sessions and having each of
them INSERT the same primary key:

* ``manga.py`` built ``celery_task_kwargs`` with ``get_or_create_system_state(db)``
  on the request's own read session. Being an argument expression it is
  evaluated *eagerly*, before the fetch callback ever runs. ``get_or_create_...``
  does ``session.add()`` + ``session.flush()`` — the INSERT is issued but never
  committed, because ``get_read_db`` only closes its session — so the row lock
  was held for the rest of the request.
* The fetch callback then opened a *separate* ``SessionLocal()`` and called
  ``get_or_create_system_state`` again, which blocked on that uncommitted
  unique-index lock.

The request was therefore waiting on a transaction belonging to itself, and only
PostgreSQL's ``statement_timeout`` (5000ms) broke the deadlock — hence the flat,
reproducible 5.00s.

A note on what these tests can and cannot prove
-----------------------------------------------
Asserting "no ``system_state`` row was created" is *not* a valid check: neither
session ever commits, so no row is left behind either way and such a test passes
against the broken code. The defect is the uncommitted INSERT's *lock*, not a
persisted row.

So the deterministic tests below assert the structural property instead — that
the read path no longer reaches for the creating helper at all — and the real
deadlock is reproduced by an ``infrastructure``-marked test against PostgreSQL,
which is the only engine whose locking and ``statement_timeout`` can express it.

Each test uses a distinct ``q`` value because ``cached_with_swr`` caches the
listing payload in a live Redis, and a shared cache key otherwise lets one test
serve another's stale response.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import backend_fastapi.app.api.routers.manga as manga_router
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import SystemState


def _clear_system_state() -> None:
    session = SessionLocal()
    try:
        session.query(SystemState).delete()
        session.commit()
    finally:
        session.close()


def test_read_only_helper_does_not_create_the_row(fastapi_app) -> None:
    """``get_system_state`` must never insert — it runs on read sessions.

    Takes ``fastapi_app`` purely so the schema exists; the helper itself is
    exercised directly against a session.
    """

    from backend_fastapi.app.services.system_state import get_system_state

    _clear_system_state()

    session = SessionLocal()
    try:
        assert get_system_state(session) is None
        # A creating helper would leave a pending INSERT on this session; on
        # PostgreSQL that is precisely the lock that deadlocks the request.
        assert not session.new, (
            "the read-only helper staged an INSERT on a read session"
        )
        session.commit()
    finally:
        session.close()


def test_manga_read_path_does_not_import_the_creating_helper() -> None:
    """The listing module must not reach for ``get_or_create_system_state``.

    This is the structural form of the defect and the one assertion that
    reliably separates fixed from broken: pre-fix the name is bound in the
    router's namespace and called twice per request, once on a read session.
    """

    assert not hasattr(manga_router, "get_or_create_system_state"), (
        "manga router still binds get_or_create_system_state. A read endpoint "
        "must not create rows: the uncommitted INSERT holds a unique-index "
        "lock that the request's own second session then blocks on, producing "
        "a 5s statement-timeout 504 on every request."
    )


def test_manga_list_serves_with_no_system_state_row(fastapi_app) -> None:
    """The listing must serve normally when the singleton row is absent."""

    _clear_system_state()

    with TestClient(fastapi_app) as client:
        response = client.get("/api/v1/manga/", params={"q": "f63-list-norow"})

    assert response.status_code == 200, (
        f"GET /api/v1/manga/ returned {response.status_code}: {response.text}"
    )
    # The retired secret-phrase flag is no longer read or reported at all.
    assert "secret_phrase_used" not in response.json()


def test_manga_browse_serves_with_no_system_state_row(fastapi_app) -> None:
    """``/manga/browse`` shares the implementation and the same defect."""

    _clear_system_state()

    with TestClient(fastapi_app) as client:
        response = client.get(
            "/api/v1/manga/browse", params={"q": "f63-browse-norow"}
        )

    assert response.status_code == 200, (
        f"GET /api/v1/manga/browse returned {response.status_code}: "
        f"{response.text}"
    )


@pytest.mark.infrastructure
def test_manga_list_does_not_deadlock_on_postgres() -> None:
    """Reproduce the real defect: no row, real PostgreSQL, real locking.

    Pre-fix this returns 504 after a flat ~5.00s as ``statement_timeout``
    cancels the blocked INSERT. This is the only test that exercises the actual
    failure rather than its structural cause, and it needs a running instance.
    """

    import os
    import urllib.error
    import urllib.request

    base_url = os.getenv("AUDIT_BASE_URL", "http://127.0.0.1:8000")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url or database_url.startswith("sqlite"):
        pytest.skip("requires a real PostgreSQL deployment")

    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM system_state"))

    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=5):
            pass
    except Exception:  # pragma: no cover - only when nothing is serving
        pytest.skip(f"no live backend at {base_url}")

    started = time.time()
    try:
        with urllib.request.urlopen(
            f"{base_url}/api/v1/manga/?q=f63-deadlock", timeout=20
        ) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        status_code = exc.code
    elapsed = time.time() - started

    assert status_code == 200, (
        f"GET /api/v1/manga/ returned {status_code} after {elapsed:.2f}s with "
        "no system_state row — the self-deadlock is still present"
    )
    assert elapsed < 4.0, (
        f"GET /api/v1/manga/ took {elapsed:.2f}s, consistent with blocking on "
        "the statement timeout rather than serving normally"
    )
