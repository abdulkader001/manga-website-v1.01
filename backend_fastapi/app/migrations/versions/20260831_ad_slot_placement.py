"""Add placement, ordering and sizing columns to ad_slots.

Lets admins assign a slot to a named page region (and size it) from the admin
panel instead of a developer hard-coding the slot into a page.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260831_ad_slot_placement"
down_revision = "20260830_drop_social_links"
branch_labels = None
depends_on = None

_NEW_COLUMNS = ("placement", "position", "height_px", "max_width_px")


def _existing_columns(bind) -> set[str]:
    inspector = inspect(bind)
    return {col["name"] for col in inspector.get_columns("ad_slots")}


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_slots"):
        return

    existing = _existing_columns(bind)

    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        if "placement" not in existing:
            batch_op.add_column(sa.Column("placement", sa.String(length=50), nullable=True))
        if "position" not in existing:
            batch_op.add_column(
                sa.Column(
                    "position",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        if "height_px" not in existing:
            batch_op.add_column(sa.Column("height_px", sa.Integer(), nullable=True))
        if "max_width_px" not in existing:
            batch_op.add_column(sa.Column("max_width_px", sa.Integer(), nullable=True))

    if "placement" not in existing:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("ad_slots")}
        if "ix_ad_slots_placement" not in existing_indexes:
            op.create_index("ix_ad_slots_placement", "ad_slots", ["placement"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_slots"):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("ad_slots")}
    if "ix_ad_slots_placement" in existing_indexes:
        op.drop_index("ix_ad_slots_placement", table_name="ad_slots")

    existing = _existing_columns(bind)
    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        for column in _NEW_COLUMNS:
            if column in existing:
                batch_op.drop_column(column)
