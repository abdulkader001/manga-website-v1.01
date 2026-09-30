"""Create ad_slots and global_ad_providers tables"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250930_create_ad_slots_table"
down_revision = "20250925_seed_footer_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("adslot") and not inspector.has_table("ad_slots"):
        op.rename_table("adslot", "ad_slots")
    elif not inspector.has_table("ad_slots"):
        op.create_table(
            "ad_slots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("html_code", sa.Text(), nullable=False),
        )

    if not inspector.has_table("global_ad_providers"):
        op.create_table(
            "global_ad_providers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), unique=True, nullable=False),
            sa.Column("config", sa.JSON(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("ad_slots"):
        op.drop_table("ad_slots")

    if inspector.has_table("global_ad_providers"):
        op.drop_table("global_ad_providers")
