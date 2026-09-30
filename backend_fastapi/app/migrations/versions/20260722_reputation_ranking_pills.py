"""Reputation, cultivation ranking, Pills, custom emojis, meme uploads (SRS Part 3)

Adds custom_emojis, reputation_events, pills, cultivation_realms,
meme_uploads; adds translation_cache.contributed_by_user_id (3C.3 Pill
minting) and user_processing_settings.auto_translate_comments (3A.5).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260722_reputation_ranking_pills"
down_revision = "20260722_native_comments_core"
branch_labels = None
depends_on = None


def _columns(inspector, table) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tc_cols = _columns(inspector, "translation_cache")
    if tc_cols and "contributed_by_user_id" not in tc_cols:
        op.add_column(
            "translation_cache",
            sa.Column("contributed_by_user_id", sa.Integer(), nullable=True),
        )

    ups_cols = _columns(inspector, "user_processing_settings")
    if ups_cols and "auto_translate_comments" not in ups_cols:
        op.add_column(
            "user_processing_settings",
            sa.Column(
                "auto_translate_comments",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )

    if not inspector.has_table("custom_emojis"):
        op.create_table(
            "custom_emojis",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("shortcode", sa.String(64), nullable=False, unique=True),
            sa.Column("image_url", sa.String(500), nullable=False),
            sa.Column(
                "category", sa.String(50), nullable=False, server_default="custom"
            ),
            sa.Column(
                "created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )

    if not inspector.has_table("reputation_events"):
        op.create_table(
            "reputation_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("ref_type", sa.String(32), nullable=True),
            sa.Column("ref_id", sa.String(64), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "ix_reputation_events_user", "reputation_events", ["user_id", "created_at"]
        )

    if not inspector.has_table("pills"):
        op.create_table(
            "pills",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("target_lang", sa.String(16), nullable=False),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="unclaimed"
            ),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_reason", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "uq_pill_user_chapter_lang",
            "pills",
            ["user_id", "chapter_id", "target_lang"],
            unique=True,
        )

    if not inspector.has_table("cultivation_realms"):
        op.create_table(
            "cultivation_realms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_index", sa.Integer(), nullable=False, unique=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("stage_count", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("reputation_threshold", sa.Integer(), nullable=False),
            sa.Column(
                "color_band", sa.String(30), nullable=False, server_default="gray"
            ),
            sa.Column(
                "dedicated_contributor",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    if not inspector.has_table("meme_uploads"):
        op.create_table(
            "meme_uploads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "uploader_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("url", sa.String(500), nullable=False),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("byte_size", sa.Integer(), nullable=True),
            sa.Column("removed_at", sa.DateTime(), nullable=True),
            sa.Column("removed_reason", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in (
        "meme_uploads",
        "cultivation_realms",
        "pills",
        "reputation_events",
        "custom_emojis",
    ):
        if inspector.has_table(table):
            op.drop_table(table)

    ups_cols = _columns(inspector, "user_processing_settings")
    if "auto_translate_comments" in ups_cols:
        op.drop_column("user_processing_settings", "auto_translate_comments")

    tc_cols = _columns(inspector, "translation_cache")
    if "contributed_by_user_id" in tc_cols:
        op.drop_column("translation_cache", "contributed_by_user_id")
