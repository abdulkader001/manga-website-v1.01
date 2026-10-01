"""Reader overlay settings: auto-translate, target language, colours, context AI.

Revision ID: 20261006_reader_overlay_settings
Revises: 20261005_local_ocr_default_on
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261006_reader_overlay_settings"
down_revision = "20261005_local_ocr_default_on"
branch_labels = None
depends_on = None

TABLE = "user_processing_settings"

COLUMNS = (
    sa.Column("overlay_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("target_language", sa.String(length=8), nullable=False, server_default="en"),
    sa.Column("overlay_text_color", sa.String(length=7), nullable=True),
    sa.Column("overlay_box_color", sa.String(length=7), nullable=True),
    sa.Column("overlay_box_opacity", sa.Integer(), nullable=False, server_default="100"),
    sa.Column("context_translation", sa.Boolean(), nullable=False, server_default=sa.true()),
)


def _existing() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _existing()
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column(TABLE, column)


def downgrade() -> None:
    existing = _existing()
    for column in reversed(COLUMNS):
        if column.name in existing:
            op.drop_column(TABLE, column.name)
