"""Increase alembic_version version_num length"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250909_increase_alembic_version_length"
down_revision = "20250909_sync_models"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    if bind.dialect.name != "sqlite":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    if bind.dialect.name != "sqlite":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
