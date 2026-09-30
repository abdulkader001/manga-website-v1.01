"""Safely rename provider_id → provider on provider_credentials"""

from alembic import op
from sqlalchemy import inspect

revision = "20251221_rename_provider_credentials_provider_column"
down_revision = "20251220_add_approved_source_domains"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("provider_credentials")]

    if "provider_id" in cols and "provider" not in cols:
        op.alter_column(
            "provider_credentials", "provider_id", new_column_name="provider"
        )
        print("✅ provider_id renamed to provider")
    else:
        print("⚠️ Skipping rename: provider_id not found or already renamed")


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("provider_credentials")]

    if "provider" in cols and "provider_id" not in cols:
        op.alter_column(
            "provider_credentials", "provider", new_column_name="provider_id"
        )
        print("✅ provider renamed back to provider_id")
    else:
        print("⚠️ Skipping downgrade: already reverted or column missing")
