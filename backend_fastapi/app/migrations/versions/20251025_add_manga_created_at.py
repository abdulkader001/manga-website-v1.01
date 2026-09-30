"""Add created_at column to manga and backfill values"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import column, inspect, table

revision = "20251025_add_manga_created_at"
down_revision = "20251020_add_manga_slug_and_indexes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("manga"):
        return

    if "created_at" not in {col["name"] for col in inspector.get_columns("manga")}:
        op.add_column("manga", sa.Column("created_at", sa.DateTime(), nullable=True))

    manga_table = table(
        "manga",
        column("created_at", sa.DateTime()),
        column("updated_at", sa.DateTime()),
        column("last_scraped", sa.DateTime()),
    )

    bind.execute(
        sa.update(manga_table).values(
            created_at=sa.func.coalesce(
                manga_table.c.created_at,
                manga_table.c.updated_at,
                manga_table.c.last_scraped,
                sa.func.now(),
            )
        )
    )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("manga", recreate="always") as batch_op:
            batch_op.alter_column(
                "created_at",
                existing_type=sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
    else:
        op.alter_column(
            "manga",
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("manga"):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("manga", recreate="always") as batch_op:
            batch_op.drop_column("created_at")
    else:
        op.drop_column("manga", "created_at")
