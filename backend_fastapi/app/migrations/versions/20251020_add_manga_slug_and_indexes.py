"""Add manga slug and supporting indexes"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251020_add_manga_slug_and_indexes"
down_revision = "20251015_add_slot_group_to_ad_slots"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("manga"):
        return

    if "slug" not in {col["name"] for col in inspector.get_columns("manga")}:
        op.add_column("manga", sa.Column("slug", sa.String(length=255), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("manga")}
    if "ix_manga_slug" not in existing_indexes:
        op.create_index("ix_manga_slug", "manga", ["slug"], unique=True)

    if inspector.has_table("chapters"):
        chapter_indexes = {index["name"] for index in inspector.get_indexes("chapters")}
        if "ix_chapters_manga_id_chapter_number" not in chapter_indexes:
            op.create_index(
                "ix_chapters_manga_id_chapter_number",
                "chapters",
                ["manga_id", "chapter_number"],
            )

    if inspector.has_table("bookmarks"):
        bookmark_indexes = {
            index["name"] for index in inspector.get_indexes("bookmarks")
        }
        if "ix_bookmarks_user_id_manga_id" not in bookmark_indexes:
            op.create_index(
                "ix_bookmarks_user_id_manga_id",
                "bookmarks",
                ["user_id", "manga_id"],
            )

    if inspector.has_table("read_history"):
        history_indexes = {
            index["name"] for index in inspector.get_indexes("read_history")
        }
        if "ix_read_history_user_id_created_at" not in history_indexes:
            op.create_index(
                "ix_read_history_user_id_created_at",
                "read_history",
                ["user_id", "created_at"],
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("read_history"):
        history_indexes = {
            index["name"] for index in inspector.get_indexes("read_history")
        }
        if "ix_read_history_user_id_created_at" in history_indexes:
            op.drop_index(
                "ix_read_history_user_id_created_at", table_name="read_history"
            )

    if inspector.has_table("bookmarks"):
        bookmark_indexes = {
            index["name"] for index in inspector.get_indexes("bookmarks")
        }
        if "ix_bookmarks_user_id_manga_id" in bookmark_indexes:
            op.drop_index("ix_bookmarks_user_id_manga_id", table_name="bookmarks")

    if inspector.has_table("chapters"):
        chapter_indexes = {index["name"] for index in inspector.get_indexes("chapters")}
        if "ix_chapters_manga_id_chapter_number" in chapter_indexes:
            op.drop_index("ix_chapters_manga_id_chapter_number", table_name="chapters")

    if inspector.has_table("manga"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("manga")}
        if "ix_manga_slug" in existing_indexes:
            op.drop_index("ix_manga_slug", table_name="manga")

        columns = {col["name"] for col in inspector.get_columns("manga")}
        if "slug" in columns:
            op.drop_column("manga", "slug")
