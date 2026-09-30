"""Add email_verified + email_verified_at to users (SRS 1D.2.4)

Verification on this platform confirms a genuine, reachable email (for
promotions/announcements). The flag is set when the user proves control (clicks
a magic link) or an OAuth provider asserts email_verified.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260705_email_verified"
down_revision = "20260630_session_policy"
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
    if not inspector.has_table(TABLE):
        return
    cols = _columns(inspector)
    if "email_verified" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "email_verified_at" not in cols:
        op.add_column(
            TABLE, sa.Column("email_verified_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = _columns(inspector)
    if "email_verified_at" in cols:
        op.drop_column(TABLE, "email_verified_at")
    if "email_verified" in cols:
        op.drop_column(TABLE, "email_verified")
