"""Sync models with DB"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250909_sync_models"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "adslot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
    )

    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.drop_table("admin_audit")
    op.drop_table("adslot")
    op.drop_table("provider_credentials")
