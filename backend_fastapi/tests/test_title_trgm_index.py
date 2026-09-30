"""Regression tests for the pg_trgm substring-title index (Gap A).

The plain btree ``ix_manga_title`` cannot serve a leading-wildcard search
(``title ILIKE '%q%'``) used by ``GET /manga``'s title filter. Migration
``20260510_add_manga_title_trgm_index`` adds a ``pg_trgm`` GIN index
(``ix_manga_title_trgm``) so the planner can use a bitmap index scan instead
of a sequential scan.

Two layers of coverage:

* A static guard that always runs (even on SQLite/CI-without-Postgres): the
  migration file must exist and define the trigram index exactly as intended.
  This protects against accidental deletion or a silently weakened index.
* A Postgres-gated runtime check that proves, via EXPLAIN, that the index can
  actually serve the substring query. It runs only when ``DATABASE_URL``
  points at a Postgres database that has had migrations applied; otherwise it
  skips (CI's pytest job runs on SQLite — the equivalent hard assertion in CI
  is ``scripts/verify_query_plans.py``, run against the migrated Postgres in
  the Backend CI workflow).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "migrations"
    / "versions"
    / "20260510_add_manga_title_trgm_index.py"
)


def test_trgm_migration_defines_expected_index() -> None:
    """Static guard — the migration exists and creates the trigram index."""

    assert MIGRATION.exists(), f"missing trigram migration: {MIGRATION}"
    source = MIGRATION.read_text(encoding="utf-8")

    # The extension and the GIN trigram index must both be created.
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in source
    assert "ix_manga_title_trgm" in source
    assert "gin (title gin_trgm_ops)" in source
    # It must chain onto the current head at authoring time, not orphan itself.
    assert 'down_revision = "20260502_encrypt_oauth_tokens"' in source
    # It must not drop the still-useful btree index.
    assert 'drop_index("ix_manga_title"' not in source


def _postgres_url() -> str | None:
    url = os.getenv("DATABASE_URL", "")
    return url if url.startswith("postgresql") else None


@pytest.mark.infrastructure
def test_trgm_index_serves_substring_search_on_postgres() -> None:
    """Runtime guard — EXPLAIN proves the trigram index serves ILIKE '%q%'.

    Skips unless DATABASE_URL is a Postgres DB whose migrations have run
    (i.e. the manga table and ix_manga_title_trgm index exist).
    """

    url = _postgres_url()
    if not url:
        pytest.skip("DATABASE_URL is not Postgres; trigram EXPLAIN check skipped")

    engine = create_engine(url, pool_pre_ping=True)
    inspector = inspect(engine)
    if "manga" not in inspector.get_table_names():
        pytest.skip("manga table absent (migrations not applied to this DB)")
    index_names = {ix["name"] for ix in inspector.get_indexes("manga")}
    if "ix_manga_title_trgm" not in index_names:
        pytest.skip(
            "ix_manga_title_trgm absent — run migrations "
            "(20260510_add_manga_title_trgm_index) against this DB first"
        )

    # Force the planner off sequential scans for the duration of this one
    # EXPLAIN so the result is independent of how many rows the table holds
    # (a near-empty CI table would otherwise seq-scan by choice). No data is
    # written; the transaction is rolled back. This proves the index *can*
    # serve the query shape, which is what the migration is accountable for.
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET LOCAL enable_seqscan = off"))
            rows = conn.execute(
                text("EXPLAIN SELECT id FROM manga WHERE title ILIKE '%naruto%'")
            ).fetchall()
        finally:
            trans.rollback()

    plan = "\n".join(str(r[-1]) if len(r) == 1 else str(tuple(r)) for r in rows)
    assert "ix_manga_title_trgm" in plan, (
        "leading-wildcard title search did not use ix_manga_title_trgm even "
        f"with seq scans disabled; plan was:\n{plan}"
    )
