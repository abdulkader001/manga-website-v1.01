"""Add bookmarks, read history, social links"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError

revision = "20250909_update_bookmarks_readhistory_sociallinks"
down_revision = "20250909_increase_alembic_version_length"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "bookmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("manga_id", sa.Integer(), sa.ForeignKey("manga.id")),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id")),
    )

    op.create_table(
        "read_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("manga_id", sa.Integer(), sa.ForeignKey("manga.id")),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    if not inspector.has_table("social_links"):
        op.create_table(
            "social_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(length=50), nullable=True),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("icon", sa.String(length=100), nullable=True),
        )
    else:
        try:
            columns = inspector.get_columns("social_links")
        except NoSuchTableError:
            columns = []
        has_icon = any(col["name"] == "icon" for col in columns)
        if not has_icon:
            # If the table predates this patch ensure the optional ``icon`` column
            # exists so the API can render a default icon identifier.
            op.add_column(
                "social_links",
                sa.Column("icon", sa.String(length=100), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.drop_table("social_links")
    op.drop_table("read_history")
    op.drop_table("bookmarks")
