"""Secret vault: admin-managed, encrypted overrides for allow-listed env vars.

Revision ID: 20261004_vault_secrets
Revises: 20261003_merge_totp_custom_tabs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261004_vault_secrets"
down_revision = "20261003_merge_totp_custom_tabs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("vault_secrets"):
        return
    op.create_table(
        "vault_secrets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("vault_secrets")
