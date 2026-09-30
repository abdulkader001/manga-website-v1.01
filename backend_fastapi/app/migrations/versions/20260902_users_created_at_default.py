"""Repair users.created_at: backfill NULLs, add the default, enforce NOT NULL (F-65)

The ORM has always declared ``created_at = Column(DateTime, server_default=func.now())``,
but no migration ever created that default on the real column. On PostgreSQL the
column therefore had no DEFAULT and was nullable, while its sibling ``updated_at``
correctly had ``now()`` and NOT NULL.

Consequence: ``ensure_magic_link_user`` (magic-link signup) and ``oauth_service``
(Google OAuth) both construct ``User(...)`` without ``created_at``, so every new
user was written with ``created_at = NULL``. ``UserRead.created_at`` is a required
``datetime``, so ``GET /auth/me`` raised ResponseValidationError -> 500 for that
user on every request, permanently. The frontend's ``AuthContext`` cannot
distinguish a 500 from a logout, so affected accounts were stuck in an
unbreakable login loop.

This migration repairs existing data and the column definition together. The
model now also carries a Python-side default so the application no longer
depends on this DDL being present.

Revision ID: 20260902_users_created_at_default
Revises: 20260901_cache_quality_gate
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902_users_created_at_default"
down_revision = "20260901_cache_quality_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    now_fn = "CURRENT_TIMESTAMP" if is_sqlite else "now()"

    # 1. Backfill rows already broken by the missing default. updated_at is a
    #    reasonable stand-in for when the row was written; fall back to the
    #    current time for any row where it is somehow also absent.
    op.execute(
        sa.text(
            f"UPDATE users SET created_at = COALESCE(updated_at, {now_fn}) "
            "WHERE created_at IS NULL"
        )
    )

    # 2. Give the column the default the ORM always claimed it had, and make a
    #    NULL impossible from here on.
    #
    #    Skipped on SQLite, which cannot ALTER COLUMN — the same guard used by
    #    20250909_increase_alembic_version_length. SQLite is only ever the
    #    test harness, and that harness builds its schema from the models via
    #    create_all, which now carries both the NOT NULL and the default.
    if not is_sqlite:
        op.alter_column(
            "users",
            "created_at",
            existing_type=sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column(
            "users",
            "created_at",
            existing_type=sa.DateTime(),
            server_default=None,
            nullable=True,
        )
