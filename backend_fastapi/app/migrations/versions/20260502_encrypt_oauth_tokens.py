"""Widen OAuth token columns for encryption at rest (Blind Spot #16)

Revision ID: 20260502_encrypt_oauth_tokens
Revises: 20260501_add_email_lookup_hash
Create Date: 2026-05-02 12:00:00.000000

OAuth access/refresh tokens are now encrypted at rest via the User model's
access_token/refresh_token properties. Ciphertext is longer than the plaintext
token, so the columns are widened from VARCHAR(255) to TEXT. Any pre-existing
plaintext values are encrypted by the resumable backfill script
``scripts/backfill_oauth_token_encryption.py`` (run after this migration).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260502_encrypt_oauth_tokens"
down_revision = "20260501_add_email_lookup_hash"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    with op.batch_alter_table("users") as batch_op:
        if _has_column(inspector, "users", "access_token"):
            batch_op.alter_column(
                "access_token",
                type_=sa.Text(),
                existing_type=sa.String(length=255),
                existing_nullable=True,
            )
        if _has_column(inspector, "users", "refresh_token"):
            batch_op.alter_column(
                "refresh_token",
                type_=sa.Text(),
                existing_type=sa.String(length=255),
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    with op.batch_alter_table("users") as batch_op:
        if _has_column(inspector, "users", "access_token"):
            batch_op.alter_column(
                "access_token",
                type_=sa.String(length=255),
                existing_type=sa.Text(),
                existing_nullable=True,
            )
        if _has_column(inspector, "users", "refresh_token"):
            batch_op.alter_column(
                "refresh_token",
                type_=sa.String(length=255),
                existing_type=sa.Text(),
                existing_nullable=True,
            )
