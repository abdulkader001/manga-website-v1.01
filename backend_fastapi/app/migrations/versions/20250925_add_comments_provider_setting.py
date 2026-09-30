"""Seed comments_provider setting"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250925_add_comments_provider_setting"
down_revision = "20250913_add_user_api_keys"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("settings"):
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO settings (key, value)
            VALUES ('comments_provider', 'internal')
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("settings"):
        return

    bind.execute(sa.text("DELETE FROM settings WHERE key = 'comments_provider'"))
