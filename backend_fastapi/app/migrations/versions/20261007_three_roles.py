"""Three roles only: retire the moderator role.

Former moderators become regular users (least privilege: they do not gain
sub-admin powers implicitly; the main admin can promote them). Their
per-person permission overrides go too -- overrides only refine sub-admins.
The moderator-only columns (assigned_to_admin_id, moderator_limit) are dropped.

Revision ID: 20261007_three_roles
Revises: 20261006_reader_overlay_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261007_three_roles"
down_revision = "20261006_reader_overlay_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    if inspector.has_table("permission_overrides"):
        op.execute(
            sa.text(
                "DELETE FROM permission_overrides WHERE user_id IN "
                "(SELECT id FROM users WHERE CAST(role AS VARCHAR) IN ('MODERATOR', 'moderator'))"
            )
        )
    op.execute(
        sa.text(
            # SQLAlchemy's Enum(UserRole) persists the member *name* ("USER").
            "UPDATE users SET role = 'USER' "
            "WHERE CAST(role AS VARCHAR) IN ('MODERATOR', 'moderator')"
        )
    )

    existing = {col["name"] for col in inspector.get_columns("users")}
    dropped = [c for c in ("assigned_to_admin_id", "moderator_limit") if c in existing]
    if dropped:
        with op.batch_alter_table("users") as batch:
            for column in dropped:
                batch.drop_column(column)


def downgrade() -> None:
    # Former moderators cannot be told apart from users afterwards; only the
    # columns come back.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("assigned_to_admin_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("moderator_limit", sa.Integer(), nullable=True))
