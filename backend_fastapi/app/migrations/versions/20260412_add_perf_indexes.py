"""Add performance indexes

Revision ID: 20260412_add_perf_indexes
Revises: 0c924aa01af3
Create Date: 2026-04-12 12:00:00.000000

"""

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260412_add_perf_indexes"
down_revision = "0c924aa01af3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # We want to index popularity desc, updated_at desc, and created_at desc
    # since these are used in get_manga_list. We will just use regular indexes.

    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_popularity" not in manga_indexes:
        op.create_index("ix_manga_popularity", "manga", ["popularity"])

    if "ix_manga_updated_at" not in manga_indexes:
        op.create_index("ix_manga_updated_at", "manga", ["updated_at"])

    if "ix_manga_created_at" not in manga_indexes:
        op.create_index("ix_manga_created_at", "manga", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    manga_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_popularity" in manga_indexes:
        op.drop_index("ix_manga_popularity", table_name="manga")

    if "ix_manga_updated_at" in manga_indexes:
        op.drop_index("ix_manga_updated_at", table_name="manga")

    if "ix_manga_created_at" in manga_indexes:
        op.drop_index("ix_manga_created_at", table_name="manga")
