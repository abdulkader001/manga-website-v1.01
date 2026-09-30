"""Merge admin audit log restructure into legacy chain"""

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "4be0d9f7edb6"
down_revision = (
    "20251019_merge_heads_fix_chain",
    "20260315_admin_audit_log_restructure",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector
    # This merge migration intentionally performs no operations.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector
    # This merge migration intentionally performs no operations.
