"""Notification system data model (SRS 1I)

Extends `notifications` with category/target/priority/read_at/dedup_key and
adds `notification_preferences` (one row per user, per-type mute/email/
digest arrays).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260811_notification_system"
down_revision = "20260810_ocr_translation_cache"
branch_labels = None
depends_on = None

TABLE = "notifications"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table(TABLE):
        existing = {c["name"] for c in inspector.get_columns(TABLE)}
        if "category" not in existing:
            op.add_column(
                TABLE,
                sa.Column(
                    "category", sa.String(16), nullable=False, server_default="reader"
                ),
            )
        if "target_type" not in existing:
            op.add_column(TABLE, sa.Column("target_type", sa.String(32), nullable=True))
        if "target_id" not in existing:
            op.add_column(TABLE, sa.Column("target_id", sa.String(64), nullable=True))
        if "read_at" not in existing:
            op.add_column(TABLE, sa.Column("read_at", sa.DateTime(), nullable=True))
        if "priority" not in existing:
            op.add_column(
                TABLE,
                sa.Column(
                    "priority", sa.String(16), nullable=False, server_default="normal"
                ),
            )
        if "dedup_key" not in existing:
            op.add_column(TABLE, sa.Column("dedup_key", sa.String(128), nullable=True))

        existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE)}
        if "ix_notifications_user_created" not in existing_indexes:
            op.create_index(
                "ix_notifications_user_created", TABLE, ["user_id", "created_at"]
            )
        if "ix_notifications_dedup" not in existing_indexes:
            op.create_index(
                "ix_notifications_dedup", TABLE, ["user_id", "type", "dedup_key"]
            )

    if not inspector.has_table("notification_preferences"):
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column(
                "global_mute",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("muted_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("email_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("digest_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("notification_preferences"):
        op.drop_table("notification_preferences")
    if inspector.has_table(TABLE):
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE)}
        if "ix_notifications_dedup" in existing_indexes:
            op.drop_index("ix_notifications_dedup", table_name=TABLE)
        if "ix_notifications_user_created" in existing_indexes:
            op.drop_index("ix_notifications_user_created", table_name=TABLE)
        existing = {c["name"] for c in inspector.get_columns(TABLE)}
        for name in (
            "dedup_key",
            "priority",
            "read_at",
            "target_id",
            "target_type",
            "category",
        ):
            if name in existing:
                op.drop_column(TABLE, name)
