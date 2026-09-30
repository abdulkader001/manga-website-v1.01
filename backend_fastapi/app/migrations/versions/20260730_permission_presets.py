"""Add permission_presets table (SRS 1F.9.3)

Custom, Permanent-Administrator-creatable presets. Built-in presets live in
code; this table holds custom ones.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260730_permission_presets"
down_revision = "20260725_remove_custom_pages"
branch_labels = None
depends_on = None

TABLE = "permission_presets"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
