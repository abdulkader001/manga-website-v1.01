"""Drop the unused ``custom_tabs`` table.

Nothing in the application reads or writes it (the custom tabs feature was
removed from the UI and API). The owner approved dropping it; any rows are
lost. ``downgrade`` recreates the empty table.

Revision ID: 20261002_drop_custom_tabs
Revises: 20261001_page_mirroring
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261002_drop_custom_tabs"
down_revision = "20261001_page_mirroring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("custom_tabs"):
        op.drop_table("custom_tabs")


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("custom_tabs"):
        return
    op.create_table(
        "custom_tabs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column(
            "is_global", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
