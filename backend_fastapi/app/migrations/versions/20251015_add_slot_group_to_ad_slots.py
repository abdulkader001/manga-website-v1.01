"""Add slot_group column to ad_slots"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251015_add_slot_group_to_ad_slots"
down_revision = "20251010_add_user_language"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_slots"):
        return

    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("slot_group", sa.String(length=100), nullable=True)
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_slots"):
        return

    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        batch_op.drop_column("slot_group")
