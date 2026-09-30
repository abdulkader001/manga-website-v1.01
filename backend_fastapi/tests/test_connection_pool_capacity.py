"""Guard against F-85: the shipped pool must not throttle the API to a crawl.

Every API endpoint is a synchronous handler that holds a pooled connection for
its whole duration, so ``SQLALCHEMY_POOL_SIZE + SQLALCHEMY_MAX_OVERFLOW`` *is*
the per-worker request concurrency ceiling.

``.env.example`` shipped ``5 + 10 = 15``, below the code's own ``20 + 10``
default. Measured live against PostgreSQL 16 on one worker, 30 concurrent
requests to ``GET /api/v1/manga/`` took over two minutes at ~1 req/s, with
callers parked on connection checkout for SQLAlchemy's 30 s default
``pool_timeout`` — six times ``REQUEST_TIMEOUT_SECONDS`` — inside uncancellable
threadpool threads, so the global 5 s timeout never shed them and not one 504
was returned. With the code default the same load completed in 1.0 s at ~30
req/s; at 50 concurrent it sustained ~130 req/s.

Separately, the pool is per *worker*: gunicorn's ``2 * cpu_count + 1`` default
multiplied by the per-worker pool exceeded PostgreSQL's default
``max_connections`` of 100 on any host with four or more cores (9 x 30 = 270),
and nothing reconciled the two.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"


def _env_example_value(name: str) -> str | None:
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


def test_env_example_pool_is_not_below_the_code_default() -> None:
    """`.env.example` is copied to `.env`, so a low value here *is* the default."""

    from backend_fastapi.app.core import db

    shipped_size = int(_env_example_value("SQLALCHEMY_POOL_SIZE"))
    shipped_overflow = int(_env_example_value("SQLALCHEMY_MAX_OVERFLOW"))

    # The code defaults live in db.py; the env file must never ship *less*.
    assert shipped_size >= 20, shipped_size
    assert shipped_size + shipped_overflow >= 30, (shipped_size, shipped_overflow)
    assert db.POOL_SIZE >= 20
    assert db.POOL_SIZE + db.MAX_OVERFLOW >= 30


def test_pool_timeout_is_not_wildly_longer_than_the_request_timeout() -> None:
    """A checkout wait far longer than the request timeout cannot be shed."""

    from backend_fastapi.app.core import db

    request_timeout = float(_env_example_value("REQUEST_TIMEOUT_SECONDS"))
    assert db.POOL_TIMEOUT <= max(request_timeout * 4, 15), (
        db.POOL_TIMEOUT,
        request_timeout,
    )


def test_engine_actually_applies_the_pool_timeout() -> None:
    """The setting has to reach create_engine, not just exist as a constant."""

    from backend_fastapi.app.core import db

    if db._is_sqlite(db.DATABASE_URL):
        pytest.skip("SQLite uses StaticPool and has no pool_timeout")
    assert db.engine.pool._timeout == db.POOL_TIMEOUT


def test_documented_worker_count_fits_the_documented_max_connections() -> None:
    """GUNICORN_WORKERS x per-worker pool must fit the compose server's ceiling."""

    workers = int(_env_example_value("GUNICORN_WORKERS"))
    size = int(_env_example_value("SQLALCHEMY_POOL_SIZE"))
    overflow = int(_env_example_value("SQLALCHEMY_MAX_OVERFLOW"))
    max_conns = int(_env_example_value("POSTGRES_MAX_CONNECTIONS"))

    demand = workers * (size + overflow)
    # Same 80% headroom the runtime check uses, leaving room for Celery,
    # the migration job and a human holding a psql session.
    assert demand <= int(max_conns * 0.8), (demand, max_conns)


def test_compose_configures_max_connections() -> None:
    """The default 100 cannot serve the documented worker/pool arithmetic."""

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "max_connections=${POSTGRES_MAX_CONNECTIONS:-300}" in compose


def test_connection_budget_reports_worker_multiplied_demand(monkeypatch) -> None:
    from backend_fastapi.app.core import db

    monkeypatch.setenv("GUNICORN_WORKERS", "7")
    workers, per_worker, total = db.connection_budget()
    assert workers == 7
    assert per_worker == db.POOL_SIZE + db.MAX_OVERFLOW
    assert total == 7 * per_worker


def test_connection_budget_falls_back_to_the_gunicorn_formula(monkeypatch) -> None:
    """A blank GUNICORN_WORKERS means gunicorn's 2 * cpu_count + 1, not 1."""

    import multiprocessing

    from backend_fastapi.app.core import db

    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    workers, _, _ = db.connection_budget()
    assert workers == 2 * multiprocessing.cpu_count() + 1


def test_budget_check_warns_when_demand_exceeds_max_connections(monkeypatch) -> None:
    from backend_fastapi.app.core import db

    if db._is_sqlite(db.DATABASE_URL):
        pytest.skip("budget check is a PostgreSQL concern")

    monkeypatch.setenv("GUNICORN_WORKERS", "50")
    message = db.check_connection_budget()
    assert message is not None
    assert re.search(r"50 workers", message)
    assert "max_connections" in message


def test_budget_check_is_quiet_when_it_fits(monkeypatch) -> None:
    from backend_fastapi.app.core import db

    if db._is_sqlite(db.DATABASE_URL):
        pytest.skip("budget check is a PostgreSQL concern")

    monkeypatch.setenv("GUNICORN_WORKERS", "1")
    assert db.check_connection_budget() is None
