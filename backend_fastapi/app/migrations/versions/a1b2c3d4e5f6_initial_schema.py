"""Create initial schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), unique=True, nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("username", sa.String(150), nullable=True),
        sa.Column("google_sub", sa.String(255), unique=True, nullable=True),
        sa.Column("permanent", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(255), nullable=False),
        sa.Column("parser_type", sa.String(100), nullable=True),
    )

    op.create_table(
        "manga",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("cover_image", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(), unique=True, nullable=False),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("type", sa.String(length=20), nullable=False, server_default="manga"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ongoing"
        ),
        sa.Column("last_chapter_at", sa.DateTime(), nullable=True),
        sa.Column("genres", sa.JSON(), nullable=True),
        sa.Column("last_scraped", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("popularity", sa.Integer(), nullable=True),
    )
    op.create_index("ix_manga_type", "manga", ["type"])
    op.create_index("ix_manga_status", "manga", ["status"])
    op.create_index("ix_manga_last_chapter_at", "manga", ["last_chapter_at"])

    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manga_id", sa.Integer(), sa.ForeignKey("manga.id"), nullable=False),
        sa.Column("chapter_number", sa.Numeric(10, 2), nullable=False),
        sa.Column("chapter_title", sa.String(), nullable=True),
        sa.Column("chapter_url", sa.String(), unique=True, nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.drop_table("chapters")
    op.drop_index("ix_manga_last_chapter_at", table_name="manga")
    op.drop_index("ix_manga_status", table_name="manga")
    op.drop_index("ix_manga_type", table_name="manga")
    op.drop_table("manga")
    op.drop_table("sources")
    op.drop_table("users")
