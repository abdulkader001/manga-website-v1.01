"""Add updated_at column to provider_credentials"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20251224_add_updated_at_to_provider_credentials"
down_revision = "20251019_fix_updated_at_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("provider_credentials"):
        columns = {col["name"] for col in inspector.get_columns("provider_credentials")}
        if "updated_at" not in columns:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("provider_credentials") as batch_op:
                    batch_op.add_column(
                        sa.Column(
                            "updated_at",
                            sa.DateTime(timezone=True),
                            nullable=True,
                            server_default=sa.text("CURRENT_TIMESTAMP"),
                        )
                    )
                op.execute(
                    sa.text(
                        "UPDATE provider_credentials SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
                    )
                )
                with op.batch_alter_table("provider_credentials") as batch_op:
                    batch_op.alter_column(
                        "updated_at",
                        server_default=None,
                    )
            else:
                op.add_column(
                    "provider_credentials",
                    sa.Column(
                        "updated_at",
                        sa.DateTime(timezone=True),
                        nullable=True,
                        server_default=sa.text("now()"),
                    ),
                )
                op.execute(
                    sa.text(
                        "UPDATE provider_credentials SET updated_at = NOW() WHERE updated_at IS NULL"
                    )
                )
                op.alter_column(
                    "provider_credentials",
                    "updated_at",
                    server_default=None,
                )
        else:
            print("⚠️ Skipping: provider_credentials.updated_at already exists")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("provider_credentials"):
        columns = {col["name"] for col in inspector.get_columns("provider_credentials")}
        if "updated_at" in columns:
            op.drop_column("provider_credentials", "updated_at")
        else:
            print("⚠️ Skipping: provider_credentials.updated_at does not exist")
