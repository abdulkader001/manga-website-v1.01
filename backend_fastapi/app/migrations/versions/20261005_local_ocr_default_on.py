"""Built-in OCR on by default.

The backend image now ships Tesseract with Korean/Japanese/Chinese data. Before
this, ``local_ocr_enabled`` could not have done anything (there was no binary),
so existing rows are switched on too; the admin can still turn it off.

Revision ID: 20261005_local_ocr_default_on
Revises: 20261004_vault_secrets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_local_ocr_default_on"
down_revision = "20261004_vault_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("system_settings"):
        return
    with op.batch_alter_table("system_settings") as batch:
        batch.alter_column(
            "local_ocr_enabled", existing_type=sa.Boolean(), server_default=sa.true()
        )
    op.execute(sa.text("UPDATE system_settings SET local_ocr_enabled = :on").bindparams(on=True))


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch:
        batch.alter_column(
            "local_ocr_enabled", existing_type=sa.Boolean(), server_default=sa.false()
        )
