"""Alembic environment configuration for the FastAPI backend."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from dotenv import load_dotenv

# Ensure the project root and app package are importable
PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    # Append, not insert(0): this must not take priority over installed
    # packages. A same-named directory at the repo root (e.g. the test-only
    # httpx/ stub in backend_fastapi/tests/conftest.py) would otherwise
    # shadow the real installed dependency of the same name for this process.
    sys.path.append(str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from backend_fastapi.app.models import Base  # noqa: E402
from backend_fastapi.app import models  # noqa: E402,F401

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Resolve the database URL strictly from the DATABASE_URL environment
    variable.

    Alembic must never silently fall back to a bundled default (e.g. a
    throwaway SQLite file) -- a misconfigured environment should fail loudly
    instead of migrating the wrong database.
    """

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required to run Alembic "
            "migrations (e.g. postgresql+psycopg2://user:pass@host:5432/dbname). "
            "Alembic does not fall back to a default database."
        )
    return database_url


# Resolved once, up front, and passed directly to SQLAlchemy below -- never
# round-tripped through `config.set_main_option`/`get_main_option`.
# ConfigParser applies %-style interpolation to option values, which would
# corrupt (and typically crash on) a URL containing a literal '%', such as a
# URL-encoded '%' in the database password.
DATABASE_URL = _get_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # `config.get_section` returns a plain dict of the already-interpolated
    # ini values; overwriting a key on that dict (rather than going back
    # through ConfigParser via set_main_option) does not get re-interpolated.
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DATABASE_URL
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        configure_kwargs = {
            "connection": connection,
            "target_metadata": target_metadata,
        }
        if connection.dialect.name == "sqlite":
            configure_kwargs["render_as_batch"] = True

        context.configure(**configure_kwargs)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
