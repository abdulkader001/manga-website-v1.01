"""Tests for the FastAPI backup and restore endpoints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.api.routers import backup as backup_router
from backend_fastapi.app.core.security import create_access_token
from _support.db_reset import clear_users

# The backup format is dialect-specific: a SQLite deployment snapshots the
# database file, a PostgreSQL one shells out to pg_dump. The suite runs
# against both (SQLite locally, PostgreSQL in CI), so the format-specific
# assertions below are marked for the engine they describe rather than
# silently failing on the other one.
_SQLITE_ONLY = pytest.mark.skipif(
    not backup_router._is_sqlite(backup_router._database_url()),
    reason="SQLite-specific backup format",
)


@pytest.fixture
def main_admin_headers():
    """Create a main admin user and return auth headers for requests."""

    session = SessionLocal()
    try:
        clear_users(session)

        user = User(
            email="admin@example.com",
            role=UserRole.ADMIN,
            is_active=True,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        token = create_access_token(str(user.id))
    finally:
        session.close()

    return {"Authorization": f"Bearer {token}"}


@_SQLITE_ONLY
def test_backup_create_returns_sqlite_snapshot(fastapi_client, main_admin_headers):
    response = fastapi_client.post("/api/backup/create", headers=main_admin_headers)
    assert response.status_code == 200

    headers = response.headers
    disposition = ""
    if hasattr(headers, "get"):
        disposition = headers.get("content-disposition") or ""
    elif isinstance(headers, list):
        for key, value in headers:
            if key.lower() == "content-disposition":
                disposition = value
                break
    assert "backup.sqlite" in disposition
    assert response.content.startswith(backup_router.SQLITE_HEADER)


def test_restore_rejects_empty_upload(fastapi_client, main_admin_headers, tmp_path):
    empty_file = tmp_path / "empty.sqlite"
    empty_file.write_bytes(b"")
    with empty_file.open("rb") as handle:
        response = fastapi_client.post(
            "/api/backup/restore",
            headers=main_admin_headers,
            files={"backup": ("empty.sqlite", handle, "application/octet-stream")},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert response.json()["error"]["details"]["reason"] == "empty_file"


def test_restore_rejects_oversized_upload(
    fastapi_client, main_admin_headers, monkeypatch, tmp_path
):
    monkeypatch.setattr(backup_router, "MAX_BACKUP_UPLOAD_SIZE", 10)

    large_file = tmp_path / "large.sqlite"
    large_file.write_bytes(backup_router.SQLITE_HEADER + b"x" * 20)
    with large_file.open("rb") as handle:
        response = fastapi_client.post(
            "/api/backup/restore",
            headers=main_admin_headers,
            files={
                "backup": (
                    "large.sqlite",
                    handle,
                    "application/octet-stream",
                )
            },
        )

    assert response.status_code == 413
    payload = response.json()
    assert payload["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert payload["error"]["details"]["reason"] == "file_too_large"


@_SQLITE_ONLY
def test_restore_rejects_invalid_sqlite_header(
    fastapi_client, main_admin_headers, tmp_path
):
    invalid_file = tmp_path / "backup.sqlite"
    invalid_file.write_bytes(b"not-a-sqlite-file")
    with invalid_file.open("rb") as handle:
        response = fastapi_client.post(
            "/api/backup/restore",
            headers=main_admin_headers,
            files={
                "backup": (
                    "backup.sqlite",
                    handle,
                    "application/octet-stream",
                )
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert response.json()["error"]["details"]["reason"] == "invalid_sqlite"


@_SQLITE_ONLY
def test_restore_accepts_valid_backup(fastapi_client, main_admin_headers, tmp_path):
    db_path = Path("test_fastapi.db")
    assert db_path.exists(), "Test database should exist"
    payload = db_path.read_bytes()

    temp_backup = tmp_path / "backup.sqlite"
    temp_backup.write_bytes(payload)
    with temp_backup.open("rb") as handle:
        response = fastapi_client.post(
            "/api/backup/restore",
            headers=main_admin_headers,
            files={
                "backup": (
                    "backup.sqlite",
                    handle,
                    "application/octet-stream",
                )
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "restored"}


# ---------------------------------------------------------------------------
# F-33: Postgres backup/restore via pg_dump/pg_restore.
#
# The main test suite runs against SQLite (see conftest.py), so these are
# gated on a *separate* env var rather than DATABASE_URL itself -- reusing
# DATABASE_URL here would flip the whole suite's db.py engine to Postgres for
# every other test in the run, not just these two.
# ---------------------------------------------------------------------------


def _backup_test_postgres_url() -> str | None:
    return os.getenv("BACKUP_TEST_POSTGRES_URL") or None


@pytest.mark.infrastructure
def test_postgres_backup_create_and_restore_round_trip(monkeypatch):
    """Runtime guard -- proves the Postgres path is real, not just gated.

    Skips unless BACKUP_TEST_POSTGRES_URL points at a reachable Postgres and
    pg_dump/pg_restore are on PATH.
    """

    url = _backup_test_postgres_url()
    if not url:
        pytest.skip("BACKUP_TEST_POSTGRES_URL not set; Postgres backup check skipped")

    monkeypatch.setattr(backup_router, "DATABASE_URL", url)

    response = backup_router._create_postgres_backup(url)
    try:
        with open(response.path, "rb") as handle:
            contents = handle.read()
    finally:
        try:
            os.remove(response.path)
        except OSError:
            pass

    assert contents.startswith(backup_router.POSTGRES_DUMP_HEADER)

    # Must not raise -- pg_restore --clean --if-exists against the same
    # database it was just dumped from.
    backup_router._restore_postgres(contents, url)


def test_postgres_backup_gates_cleanly_when_pg_dump_missing(monkeypatch):
    """F-33's documented fallback: no pg_dump on PATH -> clear 501, no crash."""

    monkeypatch.setattr(backup_router.shutil, "which", lambda name: None)

    with pytest.raises(Exception) as exc:
        backup_router._require_binary("pg_dump")
    assert getattr(exc.value, "status_code", None) == 501


@pytest.mark.skipif(
    backup_router._is_sqlite(backup_router._database_url()),
    reason="PostgreSQL-specific backup format",
)
def test_restore_rejects_a_non_pg_dump_upload(
    fastapi_client, main_admin_headers, tmp_path
):
    """The Postgres path validates the pg_dump custom-format magic (PGDMP)."""

    invalid = tmp_path / "backup.pgdump"
    invalid.write_bytes(b"not-a-pg-dump-archive")
    with invalid.open("rb") as handle:
        response = fastapi_client.post(
            "/api/backup/restore",
            headers=main_admin_headers,
            files={"backup": ("backup.pgdump", handle, "application/octet-stream")},
        )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason"] == "invalid_postgres_dump"
