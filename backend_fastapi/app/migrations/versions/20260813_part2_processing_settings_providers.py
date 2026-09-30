"""Part 2 data model: user_processing_settings + system_provider_instances

user_processing_settings backs 2A.3 (AI assistance), 2C.4.4 (voluntary cache
sharing), 2E.1/2E.1A (page/word usage limits) and 2F.2/2F.2A/2F.2B (overlay
preferences) -- one row per user, created lazily.

system_provider_instances backs 2D: multiple admin-configured providers per
service (ocr/translation/ai) with integer priority, a status lifecycle, and
usage/error statistics, alongside (not replacing) the existing single-slot
provider_credentials table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260813_part2_processing_settings_providers"
down_revision = "20260812_merge_heads_before_part2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("system_settings"):
        cols = {col["name"] for col in inspector.get_columns("system_settings")}
        if "cache_priority" not in cols:
            op.add_column(
                "system_settings",
                sa.Column(
                    "cache_priority",
                    sa.String(16),
                    nullable=False,
                    server_default="on",
                ),
            )
        if "overlay_fonts" not in cols:
            op.add_column(
                "system_settings", sa.Column("overlay_fonts", sa.JSON(), nullable=True)
            )

    if not inspector.has_table("user_processing_settings"):
        op.create_table(
            "user_processing_settings",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "usage_limit_unit",
                sa.String(8),
                nullable=False,
                server_default="pages",
            ),
            sa.Column(
                "usage_limit_window",
                sa.String(8),
                nullable=False,
                server_default="week",
            ),
            sa.Column("usage_limit_value", sa.Integer(), nullable=True),
            sa.Column(
                "usage_current", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "ai_usage_current", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "usage_period_start",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "ai_assist_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "ai_confidence_threshold",
                sa.Float(),
                nullable=False,
                server_default="0.6",
            ),
            sa.Column(
                "share_translations",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column(
                "overlay_style",
                sa.String(20),
                nullable=False,
                server_default="white_box",
            ),
            sa.Column(
                "overlay_font",
                sa.String(60),
                nullable=False,
                server_default="standard_sans",
            ),
            sa.Column(
                "overlay_font_size",
                sa.Integer(),
                nullable=False,
                server_default="20",
            ),
            sa.Column(
                "translate_sound_effects",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not inspector.has_table("system_provider_instances"):
        op.create_table(
            "system_provider_instances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider_name", sa.String(120), nullable=False),
            sa.Column("service", sa.String(16), nullable=False),
            sa.Column("provider_id", sa.String(64), nullable=False),
            sa.Column("api_url", sa.String(500), nullable=True),
            sa.Column("api_key", sa.String(255), nullable=True),
            sa.Column("website_url", sa.String(500), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="inactive"
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("usage_stats", sa.JSON(), nullable=True),
            sa.Column("error_stats", sa.JSON(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("last_health_check_at", sa.DateTime(), nullable=True),
            sa.Column(
                "rotation_counter", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "created_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_system_provider_instances_service_priority",
            "system_provider_instances",
            ["service", "priority"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("system_provider_instances"):
        op.drop_table("system_provider_instances")
    if inspector.has_table("user_processing_settings"):
        op.drop_table("user_processing_settings")
    if inspector.has_table("system_settings"):
        cols = {col["name"] for col in inspector.get_columns("system_settings")}
        if "overlay_fonts" in cols:
            op.drop_column("system_settings", "overlay_fonts")
        if "cache_priority" in cols:
            op.drop_column("system_settings", "cache_priority")
