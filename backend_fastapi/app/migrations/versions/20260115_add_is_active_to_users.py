"""Add is_active column to users"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260115_add_is_active_to_users"
down_revision = "20251224_add_updated_at_to_provider_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("users"):
        columns = {column["name"] for column in inspector.get_columns("users")}
    else:
        columns = set()

    if "is_active" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        op.execute(sa.text("UPDATE users SET is_active = true WHERE is_active IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("users"):
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_active" in columns:
            op.drop_column("users", "is_active")
