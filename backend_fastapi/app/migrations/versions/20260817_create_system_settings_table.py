"""Create system_settings table (was previously created out-of-band)

Prior to this migration, ``system_settings`` was never created by Alembic --
it was created at app boot time by
``provider_registry.check_configured_providers()`` via
``SystemSettings.__table__.create(bind, checkfirst=True)``. A database
migrated with Alembic alone (no app boot) was therefore missing the table
entirely, and every later migration that ALTERs ``system_settings``
(20260630_session_policy, 20260813_part2_processing_settings_providers,
20260816_platform_ceiling) silently no-ops when the table doesn't exist yet.

This migration creates the table so ``alembic upgrade head`` alone produces
a complete schema. It is idempotent: environments where the boot-time DDL
already created the table (and where the later ALTER migrations above have
therefore already run against it) upgrade cleanly with no changes.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260817_create_system_settings_table"
down_revision = "20260723_index_comments_table"
branch_labels = None
depends_on = None

TABLE = "system_settings"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "local_ocr_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("local_ocr_engine", sa.String(100), nullable=True),
        sa.Column(
            "session_expiry_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
        sa.Column(
            "magic_link_ttl_minutes",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "cache_priority",
            sa.String(16),
            nullable=False,
            server_default="on",
        ),
        sa.Column("overlay_fonts", sa.JSON(), nullable=True),
        sa.Column("platform_default_daily_ceiling", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
