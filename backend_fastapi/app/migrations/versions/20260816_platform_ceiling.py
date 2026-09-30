"""Global platform-default usage ceiling (SRS 2E.3)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260816_platform_ceiling"
down_revision = "20260815_series_glossary"
branch_labels = None
depends_on = None

TABLE = "system_settings"
COLUMN = "platform_default_daily_ceiling"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN not in cols:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN in cols:
        op.drop_column(TABLE, COLUMN)
