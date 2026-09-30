"""Seed footer settings"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250925_seed_footer_settings"
down_revision = "20250925_create_comments_table"
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
            INSERT INTO settings (key, value) VALUES
                ('footer_contact', 'Contact us at: support@example.com'),
                ('footer_terms', 'These are the Terms & Conditions.'),
                ('footer_privacy', 'This is the Privacy Policy.')
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("settings"):
        return

    bind.execute(
        sa.text(
            """
            DELETE FROM settings
            WHERE key IN ('footer_contact', 'footer_terms', 'footer_privacy')
            """
        )
    )
