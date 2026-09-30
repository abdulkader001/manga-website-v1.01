"""Native comment system core (SRS Part 3 / 3A)

Adds threading, edit/delete, moderator-removal, translation, and attachment
columns to `comments`; adds community moderation + reputation columns to
`users`; and creates comment_votes, comment_reactions, content_reports, and
comment_translations.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260722_native_comments_core"
down_revision = "20260816_platform_ceiling"
branch_labels = None
depends_on = None

USERS = "users"
COMMENTS = "comments"


def _columns(inspector, table) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    user_cols = _columns(inspector, USERS)
    if "reputation" not in user_cols:
        op.add_column(
            USERS,
            sa.Column("reputation", sa.Integer(), nullable=False, server_default="0"),
        )
    if "community_blocked_at" not in user_cols:
        op.add_column(
            USERS, sa.Column("community_blocked_at", sa.DateTime(), nullable=True)
        )
    if "community_blocked_reason" not in user_cols:
        op.add_column(
            USERS, sa.Column("community_blocked_reason", sa.String(255), nullable=True)
        )
    if "community_blocked_by_id" not in user_cols:
        op.add_column(
            USERS, sa.Column("community_blocked_by_id", sa.Integer(), nullable=True)
        )
    if "community_timeout_until" not in user_cols:
        op.add_column(
            USERS, sa.Column("community_timeout_until", sa.DateTime(), nullable=True)
        )
    if "community_timeout_reason" not in user_cols:
        op.add_column(
            USERS, sa.Column("community_timeout_reason", sa.String(255), nullable=True)
        )

    comment_cols = _columns(inspector, COMMENTS)
    if comment_cols:
        if "parent_id" not in comment_cols:
            op.add_column(COMMENTS, sa.Column("parent_id", sa.Integer(), nullable=True))
        if "depth" not in comment_cols:
            op.add_column(
                COMMENTS,
                sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
            )
        if "edited_at" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("edited_at", sa.DateTime(), nullable=True)
            )
        if "deleted_at" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("deleted_at", sa.DateTime(), nullable=True)
            )
        if "removed_at" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("removed_at", sa.DateTime(), nullable=True)
            )
        if "removed_by_id" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("removed_by_id", sa.Integer(), nullable=True)
            )
        if "removed_reason" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("removed_reason", sa.String(255), nullable=True)
            )
        if "source_language" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("source_language", sa.String(16), nullable=True)
            )
        if "like_count" not in comment_cols:
            op.add_column(
                COMMENTS,
                sa.Column(
                    "like_count", sa.Integer(), nullable=False, server_default="0"
                ),
            )
        if "dislike_count" not in comment_cols:
            op.add_column(
                COMMENTS,
                sa.Column(
                    "dislike_count", sa.Integer(), nullable=False, server_default="0"
                ),
            )
        if "attachment_type" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("attachment_type", sa.String(16), nullable=True)
            )
        if "attachment_url" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("attachment_url", sa.String(1000), nullable=True)
            )
        if "attachment_metadata" not in comment_cols:
            op.add_column(
                COMMENTS, sa.Column("attachment_metadata", sa.JSON(), nullable=True)
            )
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(COMMENTS)}
        if "ix_comments_parent_id" not in existing_indexes:
            op.create_index("ix_comments_parent_id", COMMENTS, ["parent_id"])
        if "ix_comments_target" not in existing_indexes:
            op.create_index(
                "ix_comments_target", COMMENTS, ["target_type", "target_id"]
            )

    if not inspector.has_table("comment_votes"):
        op.create_table(
            "comment_votes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "comment_id",
                sa.Integer(),
                sa.ForeignKey("comments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("value", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "uq_comment_vote_user",
            "comment_votes",
            ["comment_id", "user_id"],
            unique=True,
        )

    if not inspector.has_table("comment_reactions"):
        op.create_table(
            "comment_reactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "comment_id",
                sa.Integer(),
                sa.ForeignKey("comments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("emoji", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "uq_comment_reaction",
            "comment_reactions",
            ["comment_id", "user_id", "emoji"],
            unique=True,
        )

    if not inspector.has_table("content_reports"):
        op.create_table(
            "content_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("target_type", sa.String(16), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column(
                "reporter_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("reason", sa.String(255), nullable=True),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="pending"
            ),
            sa.Column(
                "resolved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_content_reports_status", "content_reports", ["status"])
        op.create_index(
            "ix_content_reports_target", "content_reports", ["target_type", "target_id"]
        )

    if not inspector.has_table("comment_translations"):
        op.create_table(
            "comment_translations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "comment_id",
                sa.Integer(),
                sa.ForeignKey("comments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("target_lang", sa.String(16), nullable=False),
            sa.Column("translated_content", sa.Text(), nullable=False),
            sa.Column("provider", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("last_accessed_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "uq_comment_translation_lang",
            "comment_translations",
            ["comment_id", "target_lang"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in (
        "comment_translations",
        "content_reports",
        "comment_reactions",
        "comment_votes",
    ):
        if inspector.has_table(table):
            op.drop_table(table)

    comment_cols = _columns(inspector, COMMENTS)
    if comment_cols:
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(COMMENTS)}
        if "ix_comments_target" in existing_indexes:
            op.drop_index("ix_comments_target", table_name=COMMENTS)
        if "ix_comments_parent_id" in existing_indexes:
            op.drop_index("ix_comments_parent_id", table_name=COMMENTS)
        for name in (
            "attachment_metadata",
            "attachment_url",
            "attachment_type",
            "dislike_count",
            "like_count",
            "source_language",
            "removed_reason",
            "removed_by_id",
            "removed_at",
            "deleted_at",
            "edited_at",
            "depth",
            "parent_id",
        ):
            if name in comment_cols:
                op.drop_column(COMMENTS, name)

    user_cols = _columns(inspector, USERS)
    for name in (
        "community_timeout_reason",
        "community_timeout_until",
        "community_blocked_by_id",
        "community_blocked_reason",
        "community_blocked_at",
        "reputation",
    ):
        if name in user_cols:
            op.drop_column(USERS, name)
