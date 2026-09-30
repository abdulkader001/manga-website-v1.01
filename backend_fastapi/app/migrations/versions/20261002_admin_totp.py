"""Admin second factor: TOTP secret, enabled flag and last accepted step.

Revision ID: 20261002_admin_totp
Revises: 20261001_page_mirroring
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261002_admin_totp"
down_revision = "20261001_page_mirroring"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("users", "totp_secret"):
        op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    if not _has_column("users", "totp_enabled"):
        op.add_column(
            "users",
            sa.Column(
                "totp_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _has_column("users", "totp_last_step"):
        op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for column in ("totp_last_step", "totp_enabled", "totp_secret"):
        if _has_column("users", column):
            op.drop_column("users", column)
