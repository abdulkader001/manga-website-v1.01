"""Add unique constraint on ScrapingJob URL"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "20250910_add_unique_scrapingjob_url"
down_revision = "20250909_update_bookmarks_readhistory_sociallinks"
branch_labels = None
depends_on = None


def create_version_aware_unique_index(table: str, column: str, index_name: str) -> None:
    """Create a unique index that handles NULL semantics for PG14 vs PG15."""

    conn = op.get_bind()
    dialect = conn.dialect.name

    op.execute(f"DROP INDEX IF EXISTS {index_name};")

    if dialect != "postgresql":
        op.create_index(index_name, table, [column], unique=True)
        return

    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_{table}_{column};")

    vnum = int(conn.execute(text("SHOW server_version_num")).scalar())
    if vnum >= 150000:
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table} ({column}) NULLS NOT DISTINCT;
            """
        )
    else:
        # PG14 lacks NULLS NOT DISTINCT, so emulate "unique when NOT NULL" with a
        # partial unique index instead.
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table} ({column})
            WHERE {column} IS NOT NULL;
            """
        )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "scraping_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id")),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_chapter_number", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )

    op.execute("DROP INDEX IF EXISTS ix_scraping_jobs_source_url_unique;")

    create_version_aware_unique_index(
        "scraping_jobs", "source_url", "ux_scraping_jobs_source_url"
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.execute("DROP INDEX IF EXISTS ux_scraping_jobs_source_url;")
    op.execute("DROP INDEX IF EXISTS ix_scraping_jobs_source_url_unique;")

    op.drop_table("scraping_jobs")
