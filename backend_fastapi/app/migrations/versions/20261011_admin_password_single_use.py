"""Admin sign-in password is single-use.

Revision ID: 20261011_admin_password_single_use
Revises: 20261010_email_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261011_admin_password_single_use"
down_revision = "20261010_email_identity"
branch_labels = None
depends_on = None

TABLE = "system_settings"
COLUMN = "admin_setup_password_used"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    if COLUMN not in {c["name"] for c in inspector.get_columns(TABLE)}:
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    if COLUMN in {c["name"] for c in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, COLUMN)
