"""Admin -> Error Report: the ``error_reports`` table.

Owner's request (2026-10-03): one admin tab listing the errors the site hit
(server, background workers and readers' browsers), grouped, each with a likely
cause and a suggested fix. No visitor IP, account or query string is stored.

Revision ID: 20261018_error_reports
Revises: 20261017_login_required_default_off
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261018_error_reports"
down_revision = "20261017_login_required_default_off"
branch_labels = None
depends_on = None

TABLE = "error_reports"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("category", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("fix", sa.Text(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
    )
    op.create_index("ix_error_reports_last_seen", TABLE, ["last_seen"])


def downgrade() -> None:
    # Lossy: the recorded errors are dropped with the table.
    if not sa.inspect(op.get_bind()).has_table(TABLE):
        return
    op.drop_index("ix_error_reports_last_seen", table_name=TABLE)
    op.drop_table(TABLE)
