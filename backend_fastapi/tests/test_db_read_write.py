"""Tests for the read/write engine split and connection hardening (item 32)."""

from __future__ import annotations

from backend_fastapi.app.core import db as db_module


def test_read_engine_falls_back_to_primary_without_replica():
    # No DATABASE_READ_URL is configured in the test env, so the read engine must
    # be the same object as the primary (zero behaviour change).
    assert db_module.read_engine is db_module.engine
    assert db_module.ReadSessionLocal is not None


def test_get_read_db_yields_a_session():
    gen = db_module.get_read_db()
    session = next(gen)
    try:
        assert session.get_bind() is db_module.read_engine
    finally:
        gen.close()


def test_postgres_connect_args_include_both_timeouts():
    args = db_module._connect_args("postgresql+psycopg2://u:p@h:5432/db")
    options = args.get("options", "")
    assert "statement_timeout=" in options
    assert "idle_in_transaction_session_timeout=" in options


def test_sqlite_connect_args_have_no_pg_options():
    args = db_module._connect_args("sqlite:///./x.db")
    assert "options" not in args
    assert args.get("check_same_thread") is False


def test_pool_defaults_are_small():
    # Intended to sit behind PgBouncer; large per-worker pools exhaust Postgres.
    assert db_module.POOL_SIZE <= 20
    assert db_module.MAX_OVERFLOW <= 20
