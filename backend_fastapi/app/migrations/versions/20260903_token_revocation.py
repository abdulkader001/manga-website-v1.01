"""Server-side token revocation: revoked_tokens + users.sessions_revoked_before

Access and refresh tokens are stateless JWTs: once signed they are valid until
they expire, and nothing the server does can take that back. ``POST
/auth/logout`` therefore only cleared the browser's cookies — a refresh token
captured off the wire or left behind in a stolen browser profile stayed usable
for the entire configured session length (1–30 days, admin-configurable).

Two mechanisms, deliberately different in cost:

* ``revoked_tokens`` — a per-token denylist keyed on the new ``jti`` claim.
  Written on logout and on each refresh-token rotation. Rows are purged once
  ``expires_at`` passes, after which the signature check refuses the token on
  its own.
* ``users.sessions_revoked_before`` — a per-account cutoff for "sign out
  everywhere" and administrative revocation, so one timestamp invalidates
  every outstanding token without a row per token.

Revision ID: 20260903_token_revocation
Revises: 20260902_users_created_at_default
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260903_token_revocation"
down_revision = "20260902_users_created_at_default"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_table("revoked_tokens"):
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("token_type", sa.String(length=16), nullable=False),
            sa.Column("reason", sa.String(length=32), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column(
                "revoked_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_revoked_tokens_user_id_users",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("jti", name="uq_revoked_tokens_jti"),
        )
        # jti is the read-path lookup (once per authenticated request);
        # expires_at drives the purge; user_id supports per-account queries.
        op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"])
        op.create_index(
            "ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"]
        )
        op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])

    if not _has_column("users", "sessions_revoked_before"):
        op.add_column(
            "users",
            sa.Column("sessions_revoked_before", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("users", "sessions_revoked_before"):
        op.drop_column("users", "sessions_revoked_before")

    if _has_table("revoked_tokens"):
        op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
        op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
        op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
        op.drop_table("revoked_tokens")
