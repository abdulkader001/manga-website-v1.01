"""Add session_expiry_days + magic_link_ttl_minutes to system_settings (SRS 1D.5.1/1D.1A.3)

Session lifetime (days, 1-30, default 14) and magic-link token TTL (minutes,
5-60, default 15) are admin-configurable. Range enforcement lives in the
service layer; the columns just persist the configured values.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260630_session_policy"
down_revision = "20260620_index_audit_log"
branch_labels = None
depends_on = None

TABLE = "system_settings"


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
    if "session_expiry_days" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "session_expiry_days",
                sa.Integer(),
                nullable=False,
                server_default="14",
            ),
        )
    if "magic_link_ttl_minutes" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "magic_link_ttl_minutes",
                sa.Integer(),
                nullable=False,
                server_default="15",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = _columns(inspector)
    if "magic_link_ttl_minutes" in cols:
        op.drop_column(TABLE, "magic_link_ttl_minutes")
    if "session_expiry_days" in cols:
        op.drop_column(TABLE, "session_expiry_days")
