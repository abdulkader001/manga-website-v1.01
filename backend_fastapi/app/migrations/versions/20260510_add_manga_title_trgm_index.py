"""Add pg_trgm GIN index for substring title search (Gap A)

Revision ID: 20260510_add_manga_title_trgm_index
Revises: 20260502_encrypt_oauth_tokens
Create Date: 2026-05-10 00:00:00.000000

The plain btree ``ix_manga_title`` (added in
20260413_add_gin_and_search_indexes) serves exact/prefix lookups and
``ORDER BY title``, but cannot serve the leading-wildcard substring search
used by ``GET /manga``'s title filter (``Manga.title.ilike(f"%{q}%")`` in
``services/manga_service.get_manga_list``). Under load that query seq-scans
the manga table. A ``pg_trgm`` GIN index lets the planner use a bitmap index
scan for substring search instead; the btree index is kept for the queries
it already serves.

Requires the ``pg_trgm`` extension, which requires ``CREATE`` privileges on
the target database. If the application's DB role cannot run
``CREATE EXTENSION``, a superuser must run
``CREATE EXTENSION IF NOT EXISTS pg_trgm;`` once, out of band, before this
migration runs (human follow-up — see PR description).
"""

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260510_add_manga_title_trgm_index"
down_revision = "20260502_encrypt_oauth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # pg_trgm/GIN trigram indexes are Postgres-specific. SQLite (local
        # dev/tests) has no equivalent and continues to seq-scan for
        # substring search; that's an accepted tradeoff for the dev DB.
        return

    inspector = inspect(bind)
    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_title_trgm" in manga_indexes:
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_manga_title_trgm ON manga USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = inspect(bind)
    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_title_trgm" in manga_indexes:
        op.drop_index("ix_manga_title_trgm", table_name="manga")
    # Deliberately not dropping the pg_trgm extension itself: other objects
    # may depend on it, and CREATE EXTENSION IF NOT EXISTS is idempotent.
