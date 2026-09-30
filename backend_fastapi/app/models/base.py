import os
from sqlalchemy import MetaData
from sqlalchemy.ext.declarative import declarative_base

# ----------------
# Base metadata
# ----------------
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def resolve_database_url() -> str:
    """Resolve ``DATABASE_URL`` strictly from the environment.

    P12-B-1: this app must never silently fall back to a bundled SQLite
    default -- a deployment where ``DATABASE_URL`` is accidentally unset
    (a bad secrets-manager render, a missing k8s ``envFrom``, ...) would
    otherwise boot cleanly against an ephemeral, per-replica, non-persistent
    local file instead of refusing to start. This is the single resolver
    every module that needs the database URL calls into (previously
    ``core/db.py`` and this module each carried their own independent
    ``os.getenv("DATABASE_URL", "sqlite:///./manga.db")`` fallback); it
    mirrors ``migrations/env.py``'s own strict resolver for Alembic.
    """

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required (e.g. "
            "postgresql+psycopg2://user:pass@host:5432/dbname). The app does "
            "not fall back to a default database."
        )
    return database_url


_database_url = resolve_database_url()
if _database_url.startswith("sqlite"):
    metadata = MetaData()
else:
    metadata = MetaData(naming_convention=convention)
Base = declarative_base(metadata=metadata)
