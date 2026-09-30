"""Add GIN and search indexes

Revision ID: 20260413_add_gin_and_search_indexes
Revises: 20260412_add_perf_indexes
Create Date: 2026-04-13 12:00:00.000000

"""

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260413_add_gin_and_search_indexes"
down_revision = "20260412_add_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1. GIN index on manga.genres
    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_genres_gin" not in manga_indexes:
        # Use postgresql_ops to specify jsonb_ops for a JSON column cast if possible,
        # but the standard recommended approach for JSON data types without a default operator class in Postgres
        # is to cast it to JSONB in the index expression.
        if bind.dialect.name == "postgresql":
            op.execute(
                "CREATE INDEX ix_manga_genres_gin ON manga USING gin ((genres::jsonb))"
            )
        else:
            op.create_index(
                "ix_manga_genres_gin", "manga", ["genres"], postgresql_using="gin"
            )

    # 2. Index on manga.title
    if "ix_manga_title" not in manga_indexes:
        op.create_index("ix_manga_title", "manga", ["title"])

    # 3. Index on manga.status
    if "ix_manga_status" not in manga_indexes:
        op.create_index("ix_manga_status", "manga", ["status"])

    # 4. Index on chapters.manga_id
    chapters_indexes = {index["name"] for index in inspector.get_indexes("chapters")}
    if "ix_chapters_manga_id" not in chapters_indexes:
        op.create_index("ix_chapters_manga_id", "chapters", ["manga_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_genres_gin" in manga_indexes:
        op.drop_index("ix_manga_genres_gin", table_name="manga")

    if "ix_manga_title" in manga_indexes:
        op.drop_index("ix_manga_title", table_name="manga")

    if "ix_manga_status" in manga_indexes:
        op.drop_index("ix_manga_status", table_name="manga")

    chapters_indexes = {index["name"] for index in inspector.get_indexes("chapters")}
    if "ix_chapters_manga_id" in chapters_indexes:
        op.drop_index("ix_chapters_manga_id", table_name="chapters")
