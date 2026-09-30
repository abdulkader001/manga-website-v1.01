"""Add language column to users"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251010_add_user_language"
down_revision = "20251005_enforce_unique_phrase_hash"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.add_column(
        "users",
        sa.Column(
            "language", sa.String(length=10), nullable=False, server_default="en"
        ),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.drop_column("users", "language")
