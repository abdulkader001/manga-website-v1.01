"""Fix-button dedupe subscribers on scraping_jobs (SRS 1G.12.2A)

Everyone who clicked Fix while a rescrape was already running is subscribed
to the completion notification — all clickers are notified, not just the
first.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260807_fix_job_subscribers"
down_revision = "20260806_ingestion_error_detail"
branch_labels = None
depends_on = None

TABLE = "scraping_jobs"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    if "subscribers" not in existing:
        op.add_column(TABLE, sa.Column("subscribers", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    if "subscribers" in {c["name"] for c in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, "subscribers")
