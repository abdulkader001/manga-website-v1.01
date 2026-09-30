"""Add email_lookup_hash column for indexed login-by-email (C2)

Revision ID: 20260501_add_email_lookup_hash
Revises: 20260413_add_gin_and_search_indexes
Create Date: 2026-05-01 12:00:00.000000

NOTE: existing rows are NOT populated by this migration. Run the resumable
backfill script ``scripts/backfill_email_lookup_hash.py`` after upgrading to
populate ``email_lookup_hash`` for pre-existing users (it needs the email
encryption key to decrypt each address). Until a row is backfilled, login
falls back to the deterministic indexed ``email_hash`` lookup, so there is no
downtime.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260501_add_email_lookup_hash"
down_revision = "20260413_add_gin_and_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {col["name"] for col in inspector.get_columns("users")}
    if "email_lookup_hash" not in columns:
        op.add_column(
            "users",
            sa.Column("email_lookup_hash", sa.String(length=64), nullable=True),
        )

    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_email_lookup_hash" not in indexes:
        op.create_index(
            "ix_users_email_lookup_hash",
            "users",
            ["email_lookup_hash"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_email_lookup_hash" in indexes:
        op.drop_index("ix_users_email_lookup_hash", table_name="users")

    columns = {col["name"] for col in inspector.get_columns("users")}
    if "email_lookup_hash" in columns:
        op.drop_column("users", "email_lookup_hash")
