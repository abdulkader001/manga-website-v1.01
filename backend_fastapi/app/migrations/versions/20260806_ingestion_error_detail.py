"""Structured scrape-failure detail + submitter on scraping_jobs (SRS 1G.5)

- scraping_jobs.error_details: JSON naming the URL, missing field, selector,
  and scraper module (1G.5.4) — never a bare error string alone.
- scraping_jobs.requested_by: who submitted the manga URL; copied to the
  series' added_by when the record is created.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260806_ingestion_error_detail"
down_revision = "20260805_series_governance"
branch_labels = None
depends_on = None

TABLE = "scraping_jobs"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    if "error_details" not in existing:
        op.add_column(TABLE, sa.Column("error_details", sa.JSON(), nullable=True))
    if "requested_by" not in existing:
        op.add_column(TABLE, sa.Column("requested_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    for name in ("error_details", "requested_by"):
        if name in existing:
            op.drop_column(TABLE, name)
