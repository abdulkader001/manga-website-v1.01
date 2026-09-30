"""Add moderator role + assignment + per-person moderator limit (SRS 1F.3)

Adds the 'moderator' value to the user_roles enum (Postgres) and the
assigned_to_admin_id / moderator_limit columns to users. Additive and
non-breaking to existing roles.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260715_moderator_role"
down_revision = "20260710_permission_overrides"
branch_labels = None
depends_on = None

TABLE = "users"


def _columns(inspector) -> set[str]:
    if not inspector.has_table(TABLE):
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Add the enum value on PostgreSQL, but only if `role` is actually backed
    # by a native Postgres ENUM type. The initial schema migration created
    # `users.role` as a plain VARCHAR (validated in the ORM, not the DB), so
    # on a real deployment there is no `user_roles` type to alter - this
    # guard makes that a no-op instead of a hard failure. On SQLite the enum
    # is always a plain VARCHAR, so nothing to alter there either.
    if bind.dialect.name == "postgresql":
        enum_exists = bind.execute(
            sa.text("SELECT 1 FROM pg_type WHERE typname = 'user_roles'")
        ).first()
        if enum_exists:
            op.execute("ALTER TYPE user_roles ADD VALUE IF NOT EXISTS 'moderator'")

    if not inspector.has_table(TABLE):
        return
    cols = _columns(inspector)
    if "assigned_to_admin_id" not in cols:
        op.add_column(
            TABLE, sa.Column("assigned_to_admin_id", sa.Integer(), nullable=True)
        )
    if "moderator_limit" not in cols:
        op.add_column(TABLE, sa.Column("moderator_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = _columns(inspector)
    if "moderator_limit" in cols:
        op.drop_column(TABLE, "moderator_limit")
    if "assigned_to_admin_id" in cols:
        op.drop_column(TABLE, "assigned_to_admin_id")
    # The enum value is intentionally left in place (removing PG enum values is
    # unsafe and not required for a rollback).
