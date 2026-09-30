"""Scheduled new-chapter detection fields (SRS 1G.12A)

- approved_source_domains.check_settings: per-website JSON (interval, jitter,
  max concurrent, quiet hours, enabled toggle)
- manga.next_check_at / manga.check_interval_hours: per-series schedule and
  the per-series override that takes priority over the website default
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260808_scheduled_checks"
down_revision = "20260807_fix_job_subscribers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("approved_source_domains"):
        cols = {c["name"] for c in inspector.get_columns("approved_source_domains")}
        if "check_settings" not in cols:
            op.add_column(
                "approved_source_domains",
                sa.Column("check_settings", sa.JSON(), nullable=True),
            )

    if inspector.has_table("manga"):
        cols = {c["name"] for c in inspector.get_columns("manga")}
        if "next_check_at" not in cols:
            op.add_column(
                "manga", sa.Column("next_check_at", sa.DateTime(), nullable=True)
            )
        if "check_interval_hours" not in cols:
            op.add_column(
                "manga",
                sa.Column("check_interval_hours", sa.Integer(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("manga"):
        cols = {c["name"] for c in inspector.get_columns("manga")}
        for name in ("next_check_at", "check_interval_hours"):
            if name in cols:
                op.drop_column("manga", name)

    if inspector.has_table("approved_source_domains"):
        cols = {c["name"] for c in inspector.get_columns("approved_source_domains")}
        if "check_settings" in cols:
            op.drop_column("approved_source_domains", "check_settings")
