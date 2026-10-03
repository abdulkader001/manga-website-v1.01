"""Genre filter ignores case (plan.md P1-6): an index for it.

Genres are stored as the sources give them ("Action", "Slice of Life"), but
the filter lowercased the query and then looked for that exact key, so
``?genre=Action`` found nothing on PostgreSQL. The filter now compares the
lowercased genre list. This index on that expression keeps it fast.

PostgreSQL only; no data changes. Downgrade drops the index.

Revision ID: 20261020_genres_ci_index
Revises: 20261019_error_reports
"""

from __future__ import annotations

from alembic import op

revision = "20261020_genres_ci_index"
down_revision = "20261019_error_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_manga_genres_ci_gin "
        "ON manga USING gin ((lower(genres::text)::jsonb))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_manga_genres_ci_gin")
