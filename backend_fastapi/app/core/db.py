"""Database configuration for the FastAPI service.

Scale groundwork (item 32): the app talks to a **write** engine (``DATABASE_URL``)
and a **read** engine (``DATABASE_READ_URL``). When ``DATABASE_READ_URL`` is
unset the read engine falls back to the primary, so adding a real read replica
later is a config change rather than a code change. Read-only endpoints use
``get_read_db``; everything else uses ``get_db`` (write). Pools are kept small
(intended to sit behind PgBouncer) and Postgres connections carry both a
``statement_timeout`` and an ``idle_in_transaction_session_timeout``.
"""

from __future__ import annotations

import structlog
import os
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..models import Base
from ..models.base import resolve_database_url

# P12-B-1: no bundled SQLite default -- see resolve_database_url()'s
# docstring. A missing DATABASE_URL must fail app startup loudly, not boot
# silently against a throwaway local file.
DATABASE_URL = resolve_database_url()
# Optional read-replica URL; falls back to the primary when unset.
DATABASE_READ_URL = os.getenv("DATABASE_READ_URL") or DATABASE_URL
SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"
POOL_RECYCLE = int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "1800"))
# Keep the app-side pool small (intended behind PgBouncer). Sized per worker.
POOL_SIZE = int(os.getenv("SQLALCHEMY_POOL_SIZE", "20"))
MAX_OVERFLOW = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "10"))
# F-85: how long a request waits for a free pooled connection before giving up.
# SQLAlchemy's default is 30 s, which is six times the 5 s REQUEST_TIMEOUT_SECONDS
# -- a saturated pool therefore parked requests in an uncancellable threadpool
# thread for half a minute instead of shedding them, and the global timeout
# never got the chance to return a 504. Failing the checkout fast turns pool
# exhaustion into a prompt error the caller can retry.
POOL_TIMEOUT = int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "10"))
STATEMENT_TIMEOUT = int(os.getenv("POSTGRES_STATEMENT_TIMEOUT", "5000"))
IDLE_IN_TXN_TIMEOUT = int(os.getenv("POSTGRES_IDLE_IN_TXN_TIMEOUT", "10000"))

logger = structlog.get_logger(__name__)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _connect_args(url: str) -> dict[str, object]:
    if _is_sqlite(url):
        return {"check_same_thread": False, "timeout": 30}
    # Bound rogue queries and abandoned open transactions so a single request
    # can't hold a connection/locks indefinitely.
    options = (
        f"-c statement_timeout={STATEMENT_TIMEOUT} "
        f"-c idle_in_transaction_session_timeout={IDLE_IN_TXN_TIMEOUT}"
    )
    return {"options": options}


def _make_engine(url: str):
    kwargs = dict(
        echo=SQLALCHEMY_ECHO,
        future=True,
        pool_pre_ping=True,
        pool_recycle=POOL_RECYCLE,
        connect_args=_connect_args(url),
    )
    if _is_sqlite(url):
        kwargs.update(poolclass=StaticPool)
    else:
        kwargs.update(
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
        )
    return create_engine(url, **kwargs)


def connection_budget() -> tuple[int, int, int]:
    """Return ``(workers, per_worker, total)`` PostgreSQL connections demanded.

    Each gunicorn worker is a separate process with its own engine and its own
    pool, so the connections this service can demand is *per-worker* capacity
    multiplied by the worker count -- not the pool size on its own.
    """

    workers_raw = os.getenv("GUNICORN_WORKERS") or os.getenv("WEB_CONCURRENCY") or ""
    try:
        workers = int(workers_raw)
    except ValueError:
        workers = 0
    if workers <= 0:
        # Mirrors backend_fastapi/deployment/gunicorn.conf.py's `2 * cpu_count + 1` default.
        try:
            import multiprocessing

            workers = 2 * multiprocessing.cpu_count() + 1
        except Exception:  # pragma: no cover - defensive
            workers = 1
    per_worker = POOL_SIZE + MAX_OVERFLOW
    return workers, per_worker, workers * per_worker


def check_connection_budget() -> str | None:
    """Warn when the pool arithmetic cannot fit the server's ``max_connections``.

    F-85: nothing reconciled the gunicorn worker count, the per-worker pool and
    PostgreSQL's ``max_connections``. On a 4-core host the shipped configuration
    demanded 135 connections against a server default of 100, so under load
    workers raced each other for connections that could not exist -- and the
    failure surfaced as slow requests rather than as the configuration error it
    actually is. Returns the warning message (also logged) or None when it fits.
    """

    if _is_sqlite(DATABASE_URL):
        return None

    workers, per_worker, total = connection_budget()
    try:
        with engine.connect() as connection:
            server_max = int(
                connection.execute(text("SHOW max_connections")).scalar_one()
            )
    except SQLAlchemyError:
        # The database is unreachable or does not support SHOW; the connectivity
        # check reports that separately. Never block startup on an advisory check.
        logger.info("Could not read max_connections; connection budget unchecked")
        return None

    # Leave room for Celery workers, the migration job, backups and a human
    # holding a psql session -- the API must not be entitled to every slot.
    budget = int(server_max * 0.8)
    if total <= budget:
        return None

    message = (
        f"Database connection budget exceeded: {workers} workers x "
        f"{per_worker} connections = {total}, but max_connections is "
        f"{server_max} (usable budget {budget}). Lower GUNICORN_WORKERS or "
        f"SQLALCHEMY_POOL_SIZE/SQLALCHEMY_MAX_OVERFLOW, raise max_connections, "
        f"or put PgBouncer in front."
    )
    logger.warning(
        "database_connection_budget_exceeded",
        message=message,
        workers=workers,
        per_worker=per_worker,
        total=total,
        server_max=server_max,
    )
    return message


def _render_safe_database_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, AttributeError, TypeError):
        return "<unparseable>"


# Write (primary) engine — the default for the whole app.
engine = _make_engine(DATABASE_URL)

# Read engine — a replica when DATABASE_READ_URL is set, else the primary.
_has_replica = DATABASE_READ_URL != DATABASE_URL
read_engine = _make_engine(DATABASE_READ_URL) if _has_replica else engine

safe_db_url = _render_safe_database_url(DATABASE_URL)
if _is_sqlite(DATABASE_URL):
    logger.warning(
        "Configured database URL: %s (SQLite detected; reserve this for local development)",
        safe_db_url,
    )
else:
    logger.info("Configured database URL: %s", safe_db_url)
if _has_replica:
    logger.info(
        "Read replica configured: %s",
        _render_safe_database_url(DATABASE_READ_URL),
    )


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Read-only session factory. Bound to the replica when configured; otherwise it
# shares the primary engine, so callers can adopt it now with zero behaviour
# change and gain replica routing for free once DATABASE_READ_URL is set.
ReadSessionLocal = sessionmaker(
    bind=read_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide a read/write database session to FastAPI path operations."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_read_db() -> Generator[Session, None, None]:
    """Provide a read-only session for read-heavy endpoints (replica-routable)."""

    db = ReadSessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = [
    "Base",
    "SessionLocal",
    "ReadSessionLocal",
    "engine",
    "read_engine",
    "get_db",
    "get_read_db",
]
