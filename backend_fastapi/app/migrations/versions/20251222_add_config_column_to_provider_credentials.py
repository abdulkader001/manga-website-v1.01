"""Add config column to provider_credentials"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251222_add_config_column_to_provider_credentials"
down_revision = "20251221_rename_provider_credentials_provider_column"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {col["name"] for col in inspector.get_columns("provider_credentials")}

    if "config" not in cols:
        op.add_column(
            "provider_credentials", sa.Column("config", sa.JSON(), nullable=True)
        )
        print("✅ Added provider_credentials.config column")
    else:
        print("⚠️ Skipping: provider_credentials.config already exists")


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {col["name"] for col in inspector.get_columns("provider_credentials")}

    if "config" in cols:
        op.drop_column("provider_credentials", "config")
        print("✅ Dropped provider_credentials.config column")
    else:
        print("⚠️ Skipping: provider_credentials.config does not exist")
