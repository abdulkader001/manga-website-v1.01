"""Sign-in required is on by default, and switched on for the existing site.

The owner wants nobody to see the site before signing in. New rows start with
``system_settings.login_required`` on, and the existing row is switched on
here. The owner can still turn it off in Admin Settings.

Revision ID: 20261015_login_required_default_on
Revises: 20261014_four_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261015_login_required_default_on"
down_revision = "20261014_four_roles"
branch_labels = None
depends_on = None

TABLE = "system_settings"
COLUMN = "login_required"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(TABLE) and COLUMN in {
        c["name"] for c in inspector.get_columns(TABLE)
    }


def upgrade() -> None:
    if not _has_column():
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )
    op.execute(sa.text(f"UPDATE {TABLE} SET {COLUMN} = :on").bindparams(on=True))


def downgrade() -> None:
    # Only the default goes back. The value the owner had before the upgrade
    # is not kept, so existing rows stay as they are (turn it off in Admin
    # Settings if you want guests back).
    if not _has_column():
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
