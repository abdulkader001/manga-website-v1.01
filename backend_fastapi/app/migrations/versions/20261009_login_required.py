"""Main-admin switch that makes signing in mandatory for readers.

Revision ID: 20261009_login_required
Revises: 20261008_chapter_title_translations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261009_login_required"
down_revision = "20261008_chapter_title_translations"
branch_labels = None
depends_on = None

TABLE = "system_settings"
COLUMN = "login_required"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN not in cols:
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        # Until now every page required sign-in; keep that for sites being
        # upgraded. The main admin can switch it off in Admin Settings.
        bind = op.get_bind()
        has_row = bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first()
        if has_row:
            bind.execute(sa.text(f"UPDATE {TABLE} SET {COLUMN} = :on"), {"on": True})
        else:
            bind.execute(
                sa.text(f"INSERT INTO {TABLE} (id, {COLUMN}) VALUES (1, :on)"), {"on": True}
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN in cols:
        op.drop_column(TABLE, COLUMN)
