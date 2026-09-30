"""Disposable-email flag-for-review fields on users (SRS 1H.7.1 / D5)

D5's resolved safe default: detection flags an account for administrator
review rather than auto-banning it, avoiding false-positive lockouts on
shared networks (dormitories, offices).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260809_disposable_email_flag"
down_revision = "20260808_scheduled_checks"
branch_labels = None
depends_on = None

TABLE = "users"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    if "flagged_for_review" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "flagged_for_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "flag_reason" not in existing:
        op.add_column(TABLE, sa.Column("flag_reason", sa.String(64), nullable=True))
    if "flagged_at" not in existing:
        op.add_column(TABLE, sa.Column("flagged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    for name in ("flagged_for_review", "flag_reason", "flagged_at"):
        if name in existing:
            op.drop_column(TABLE, name)
