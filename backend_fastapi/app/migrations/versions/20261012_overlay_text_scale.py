"""Reader overlay: 1-100 text-size scale, outline colour, bubble-shape switch.

``overlay_font_size`` used to hold pixels (10-40, whole numbers). It now
holds the reader's slider value, 1-100 in half steps; the overlay draws
``value * 0.7`` px (100 -> 70 px). Existing rows are converted so every
reader keeps the size they had (20 px -> 28.5 -> 19.95 px).

Revision ID: 20261012_overlay_text_scale
Revises: 20261011_admin_password_single_use
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261012_overlay_text_scale"
down_revision = "20261011_admin_password_single_use"
branch_labels = None
depends_on = None

TABLE = "user_processing_settings"
PX_PER_STEP = 0.7

NEW_COLUMNS = (
    sa.Column("overlay_outline_color", sa.String(length=7), nullable=True),
    sa.Column("overlay_match_bubble", sa.Boolean(), nullable=False, server_default=sa.true()),
)


def _existing() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _existing()
    if not existing:
        return
    for column in NEW_COLUMNS:
        if column.name not in existing:
            op.add_column(TABLE, column)
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "overlay_font_size",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            server_default="28.5",
        )
    rows = op.get_bind().execute(sa.text(f"SELECT user_id, overlay_font_size FROM {TABLE}")).fetchall()
    for user_id, px in rows:
        scale = min(100.0, max(1.0, round((float(px or 20) / PX_PER_STEP) * 2) / 2))
        op.get_bind().execute(
            sa.text(f"UPDATE {TABLE} SET overlay_font_size = :s WHERE user_id = :u"),
            {"s": scale, "u": user_id},
        )


def downgrade() -> None:
    existing = _existing()
    if not existing:
        return
    rows = op.get_bind().execute(sa.text(f"SELECT user_id, overlay_font_size FROM {TABLE}")).fetchall()
    for user_id, scale in rows:
        px = int(min(40, max(10, round(float(scale or 28.5) * PX_PER_STEP))))
        op.get_bind().execute(
            sa.text(f"UPDATE {TABLE} SET overlay_font_size = :p WHERE user_id = :u"),
            {"p": px, "u": user_id},
        )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "overlay_font_size",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            server_default="20",
        )
    for column in reversed(NEW_COLUMNS):
        if column.name in existing:
            op.drop_column(TABLE, column.name)
