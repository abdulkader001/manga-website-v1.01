"""Site Functions (owner's on/off switches) and per-person admin tab access.

Adds ``site_functions`` (one row per function the owner changed from its
default) and two columns on ``users``: ``visible_admin_tabs`` (which admin tabs
an Admin / sub-admin may use, NULL = follow their permissions) and
``powers_suspended`` (the owner's "switch all powers off").

Revision ID: 20261016_site_functions_and_tab_access
Revises: 20261015_login_required_default_on
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_site_functions_and_tab_access"
down_revision = "20261015_login_required_default_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("site_functions"):
        op.create_table(
            "site_functions",
            sa.Column("key", sa.String(length=64), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
    if inspector.has_table("users"):
        existing = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "visible_admin_tabs" not in existing:
                batch.add_column(sa.Column("visible_admin_tabs", sa.JSON(), nullable=True))
            if "powers_suspended" not in existing:
                batch.add_column(
                    sa.Column(
                        "powers_suspended", sa.Boolean(), nullable=False, server_default=sa.false()
                    )
                )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("users"):
        existing = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "powers_suspended" in existing:
                batch.drop_column("powers_suspended")
            if "visible_admin_tabs" in existing:
                batch.drop_column("visible_admin_tabs")
    if inspector.has_table("site_functions"):
        op.drop_table("site_functions")
