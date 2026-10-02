"""Deputies and automatic succession: admin activity days + owner switch.

Revision ID: 20261013_admin_succession
Revises: 20261012_overlay_text_scale
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261013_admin_succession"
down_revision = "20261012_overlay_text_scale"
branch_labels = None
depends_on = None

SETTINGS = "system_settings"
COLUMNS = (
    sa.Column("succession_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("succession_inactive_days", sa.Integer(), nullable=False, server_default="60"),
    sa.Column("succession_enabled_at", sa.DateTime(), nullable=True),
)


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if not inspector.has_table("admin_activity_days"):
        op.create_table(
            "admin_activity_days",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("day", sa.Date(), primary_key=True),
        )
    if inspector.has_table(SETTINGS):
        existing = {c["name"] for c in inspector.get_columns(SETTINGS)}
        for column in COLUMNS:
            if column.name not in existing:
                op.add_column(SETTINGS, column)


def downgrade() -> None:
    inspector = _inspector()
    if inspector.has_table(SETTINGS):
        existing = {c["name"] for c in inspector.get_columns(SETTINGS)}
        for column in reversed(COLUMNS):
            if column.name in existing:
                op.drop_column(SETTINGS, column.name)
    if inspector.has_table("admin_activity_days"):
        op.drop_table("admin_activity_days")
