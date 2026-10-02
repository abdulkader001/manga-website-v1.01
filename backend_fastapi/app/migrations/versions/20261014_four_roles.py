"""Four roles: owner, Admin, sub-admin, user.

Adds the Admin tier (``co_admin``), the sub-admin pool columns on ``users``
(``appointed_by``, ``sub_admin_quota``, ``admin_since``), each Admin's
succession line (``admin_successors``) and the owner's ceiling on what a
sub-admin may hold (``system_settings.sub_admin_blocked_permissions``).

The earlier "deputies" (sub-admins holding site-owner powers) are not turned
into Admins automatically: that would hand them the whole Admin default, more
than the owner gave. Their stored site-owner grants are removed (a sub-admin
can no longer hold one), so they are plain sub-admins until the owner makes
them Admins in Role Management.

Revision ID: 20261014_four_roles
Revises: 20261013_admin_succession
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261014_four_roles"
down_revision = "20261013_admin_succession"
branch_labels = None
depends_on = None

# The site-owner powers at the time of this migration (a snapshot, so the
# migration never changes meaning when the catalogue does).
OWNER_POWERS = (
    "manage_secret_vault", "manage_admin_settings", "manage_cache", "purge_site_data",
    "view_providers", "manage_providers", "configure_scraper_ai", "trigger_scraper_ai",
    "manage_roles", "promote_secondary", "demote_secondary", "configure_branding",
    "manage_donations", "manage_backups", "manage_geolock", "reveal_user_email",
)

USER_COLUMNS = ("appointed_by", "sub_admin_quota", "admin_since")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Only when `users.role` is backed by a native Postgres ENUM (see
    # 20260715_moderator_role); a plain VARCHAR needs nothing.
    if bind.dialect.name == "postgresql":
        if bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'user_roles'")).first():
            with op.get_context().autocommit_block():
                op.execute("ALTER TYPE user_roles ADD VALUE IF NOT EXISTS 'CO_ADMIN'")

    if inspector.has_table("users"):
        existing = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "appointed_by" not in existing:
                batch.add_column(sa.Column("appointed_by", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_users_appointed_by", "users", ["appointed_by"], ["id"], ondelete="SET NULL")
            if "sub_admin_quota" not in existing:
                batch.add_column(sa.Column("sub_admin_quota", sa.Integer(), nullable=True))
            if "admin_since" not in existing:
                batch.add_column(sa.Column("admin_since", sa.DateTime(), nullable=True))

    if inspector.has_table("system_settings"):
        existing = {c["name"] for c in inspector.get_columns("system_settings")}
        if "sub_admin_blocked_permissions" not in existing:
            op.add_column("system_settings", sa.Column("sub_admin_blocked_permissions", sa.JSON(), nullable=True))

    if not inspector.has_table("admin_successors"):
        op.create_table(
            "admin_successors",
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("position", sa.Integer(), primary_key=True),
            sa.Column("successor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("admin_id", "successor_id", name="uq_admin_successor_person"),
        )

    # A sub-admin can no longer hold a site-owner power: drop stale grants.
    if inspector.has_table("permission_overrides") and inspector.has_table("users"):
        powers = ", ".join(f"'{key}'" for key in OWNER_POWERS)
        op.execute(
            sa.text(
                "DELETE FROM permission_overrides WHERE permission IN (" + powers + ") AND user_id IN "
                "(SELECT id FROM users WHERE CAST(role AS VARCHAR) IN ('SECONDARY', 'secondary_admin'))"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # The old code doesn't know the Admin role: Admins go back to sub-admins.
    if inspector.has_table("users"):
        op.execute(
            sa.text(
                "UPDATE users SET role = 'SECONDARY' WHERE CAST(role AS VARCHAR) IN ('CO_ADMIN', 'co_admin')"
            )
        )

    if inspector.has_table("admin_successors"):
        op.drop_table("admin_successors")

    if inspector.has_table("system_settings"):
        existing = {c["name"] for c in inspector.get_columns("system_settings")}
        if "sub_admin_blocked_permissions" in existing:
            op.drop_column("system_settings", "sub_admin_blocked_permissions")

    if inspector.has_table("users"):
        existing = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "appointed_by" in existing:
                batch.drop_constraint("fk_users_appointed_by", type_="foreignkey")
                batch.drop_column("appointed_by")
            for column in ("sub_admin_quota", "admin_since"):
                if column in existing:
                    batch.drop_column(column)
    # The enum value is intentionally left in place (removing PG enum values is unsafe).
