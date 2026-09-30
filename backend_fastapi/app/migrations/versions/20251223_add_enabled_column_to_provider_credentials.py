"""Add enabled column to provider_credentials"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251223_add_enabled_column_to_provider_credentials"
down_revision = "20251222_add_config_column_to_provider_credentials"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {col["name"] for col in inspector.get_columns("provider_credentials")}

    if "enabled" not in cols:
        op.add_column(
            "provider_credentials",
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        print("✅ Added provider_credentials.enabled column")
    else:
        print("⚠️ Skipping: provider_credentials.enabled already exists")


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {col["name"] for col in inspector.get_columns("provider_credentials")}

    if "enabled" in cols:
        op.drop_column("provider_credentials", "enabled")
        print("✅ Dropped provider_credentials.enabled column")
    else:
        print("⚠️ Skipping: provider_credentials.enabled does not exist")
