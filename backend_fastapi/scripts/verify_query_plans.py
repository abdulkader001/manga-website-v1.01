#!/usr/bin/env python3
"""Query-plan verification for the manga search fixes (Phase 4 / item 27,
extended for Gap A's pg_trgm title index).

Runs EXPLAIN on the two queries the indexing fixes target and reports/asserts
whether an index can actually serve each one, rather than a full scan:

  1. Genre filter  -> should use the ``ix_manga_genres_gin`` GIN index via the
     JSONB existence operator (``genres::jsonb ? 'action'``). Informational
     only (item 9 / H3); does not affect the exit code.
  2. Title search  -> ``title ILIKE '%q%'`` (leading wildcard) cannot use the
     plain btree ``ix_manga_title``. Migration 20260510 adds a ``pg_trgm``
     GIN index (``ix_manga_title_trgm``) for this. This check is a hard
     assertion (Gap A): on Postgres, if the trigram index cannot serve the
     query, the script exits non-zero and fails CI.

Each check runs the EXPLAIN twice:

  * "natural" plan — whatever the planner would actually pick given current
    table statistics. On a small/empty table (e.g. a freshly migrated CI
    database) the planner will often prefer a seq scan even when a usable
    index exists, simply because scanning a handful of rows is cheaper than
    an index lookup. This is informational only — it is not a reliable CI
    signal because it depends on how much data happens to be in the table.
  * "forced" plan — the same query re-planned with ``SET LOCAL
    enable_seqscan = off`` for the duration of that one EXPLAIN. This proves
    whether an index *can* serve the query shape at all, independent of row
    count, which is the actual thing a schema/index migration should be
    held to. This is what the pass/fail assertion is based on. The setting
    is reset to its default immediately after each check and no data is
    ever written, so this is safe to run against any Postgres database.

Run against a real Postgres database for a meaningful result:

    DATABASE_URL=postgresql+psycopg2://... \\
        python -m backend_fastapi.scripts.verify_query_plans

On SQLite the script still runs (EXPLAIN QUERY PLAN) but index selection is
not representative of production Postgres, and no assertion is made.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Manga
from backend_fastapi.app.services.manga_service import apply_genre_filters


def _explain(session, sql: str, *, force_index: bool = False) -> str:
    dialect = session.get_bind().dialect.name
    prefix = "EXPLAIN QUERY PLAN " if dialect == "sqlite" else "EXPLAIN "
    force_index = force_index and dialect == "postgresql"
    if force_index:
        session.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        rows = session.execute(text(prefix + sql)).fetchall()
    finally:
        if force_index:
            # Scoped to this EXPLAIN only; restore the default immediately so
            # it never affects any other query in the (shared) transaction.
            session.execute(text("SET LOCAL enable_seqscan = on"))
    return "\n".join(str(r[-1]) if len(r) == 1 else str(tuple(r)) for r in rows)


def _compiled(session, query) -> str:
    return str(
        query.statement.compile(
            session.get_bind(),
            compile_kwargs={"literal_binds": True},
        )
    )


def main() -> int:
    session = SessionLocal()
    exit_code = 0
    try:
        dialect = session.get_bind().dialect.name
        print(f"Dialect: {dialect}\n")

        # --- Genre filter (should use ix_manga_genres_gin on Postgres) ---
        genre_q = apply_genre_filters(
            session.query(Manga.id), ["action"], [], dialect_name=dialect
        )
        genre_sql = _compiled(session, genre_q)
        print("== Genre filter query ==")
        print(genre_sql)
        print("-- natural plan --")
        print(_explain(session, genre_sql))
        if dialect == "postgresql":
            forced_genre_plan = _explain(session, genre_sql, force_index=True)
            print("-- forced (enable_seqscan=off) plan --")
            print(forced_genre_plan)
            if "ix_manga_genres_gin" in forced_genre_plan:
                print(
                    "RESULT: PASS — GIN index ix_manga_genres_gin can serve this query.\n"
                )
            else:
                print(
                    "RESULT: WARN — GIN index cannot serve this query even when "
                    "forced. Ensure the 20260413 migration ran.\n"
                )

        # --- Title substring search ---
        title_q = session.query(Manga.id).filter(Manga.title.ilike("%naruto%"))
        title_sql = _compiled(session, title_q)
        print("== Title substring search query ==")
        print(title_sql)
        print("-- natural plan --")
        print(_explain(session, title_sql))
        if dialect == "postgresql":
            forced_title_plan = _explain(session, title_sql, force_index=True)
            print("-- forced (enable_seqscan=off) plan --")
            print(forced_title_plan)
            if "ix_manga_title_trgm" in forced_title_plan:
                print(
                    "RESULT: PASS — trigram index ix_manga_title_trgm can serve "
                    "leading-wildcard substring search.\n"
                )
            else:
                print(
                    "RESULT: FAIL — leading-wildcard ILIKE is not served by any "
                    "index, even with sequential scanning disabled. Ensure "
                    "migration 20260510_add_manga_title_trgm_index ran and that "
                    "the pg_trgm extension was created (CREATE EXTENSION "
                    "IF NOT EXISTS pg_trgm; requires DB-role CREATE privileges — "
                    "if the app's role lacks them, a superuser must run it once "
                    "out of band; see the migration docstring).\n"
                )
                exit_code = 1
        else:
            print(
                "NOTE: non-Postgres dialect — the pg_trgm index assertion only "
                "applies to Postgres; skipping.\n"
            )

        return exit_code
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    sys.exit(main())
