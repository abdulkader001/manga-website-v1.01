"""Index admin_audit_logs on timestamp and user_id (SRS 1C.3.5)

admin_audit_logs is a high-volume, append-only table whose partition key is
time. Without an index on ``timestamp`` its time-ordered pagination degrades to
a full scan as it grows; the ``user_id`` FK was also unindexed. Both are added
here (idempotently).
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260620_index_audit_log"
down_revision = "20260610_add_content_rights"
branch_labels = None
depends_on = None

TABLE = "admin_audit_logs"


def _existing_indexes(inspector) -> set[str]:
    if not inspector.has_table(TABLE):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = _existing_indexes(inspector)
    if "ix_admin_audit_logs_timestamp" not in existing:
        op.create_index("ix_admin_audit_logs_timestamp", TABLE, ["timestamp"])
    if "ix_admin_audit_logs_user_id" not in existing:
        op.create_index("ix_admin_audit_logs_user_id", TABLE, ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = _existing_indexes(inspector)
    if "ix_admin_audit_logs_user_id" in existing:
        op.drop_index("ix_admin_audit_logs_user_id", table_name=TABLE)
    if "ix_admin_audit_logs_timestamp" in existing:
        op.drop_index("ix_admin_audit_logs_timestamp", table_name=TABLE)
