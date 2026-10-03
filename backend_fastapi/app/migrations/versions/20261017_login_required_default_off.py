"""Sign-in required is off by default, and switched off for the existing site.

Owner's rule (2026-10-03): the site starts open, so guests can browse, read and
keep bookmarks in their browser without an account. Once the Admins are in
place the owner switches "Sign-in required" on in Admin -> Site Functions.
New rows start with ``system_settings.login_required`` off, and the existing
row is switched off here (20261015 had forced it on).

Revision ID: 20261017_login_required_default_off
Revises: 20261016_site_functions_and_tab_access
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261017_login_required_default_off"
down_revision = "20261016_site_functions_and_tab_access"
branch_labels = None
depends_on = None

TABLE = "system_settings"
COLUMN = "login_required"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(TABLE) and COLUMN in {
        c["name"] for c in inspector.get_columns(TABLE)
    }


def _set_default(value) -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=value,
        )


def upgrade() -> None:
    if not _has_column():
        return
    _set_default(sa.false())
    op.execute(sa.text(f"UPDATE {TABLE} SET {COLUMN} = :off").bindparams(off=False))


def downgrade() -> None:
    # Only the default goes back to on. The value the owner had before the
    # upgrade is not kept, so existing rows stay as they are (switch it on in
    # Admin -> Site Functions).
    if not _has_column():
        return
    _set_default(sa.true())
