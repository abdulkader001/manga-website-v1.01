"""Chapter page mirroring and layouts: keep source URLs and stored size next to
the pages, chapter grouping members, and a per-series scrape layout.

Revision ID: 20261001_page_mirroring
Revises: 20260930_reader_ui_integration
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261001_page_mirroring"
down_revision = "20260930_reader_ui_integration"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("chapters", "source_pages"):
        op.add_column("chapters", sa.Column("source_pages", sa.JSON(), nullable=True))
    if not _has_column("chapters", "pages_bytes"):
        op.add_column("chapters", sa.Column("pages_bytes", sa.Integer(), nullable=True))
    if not _has_column("chapters", "group_urls"):
        op.add_column("chapters", sa.Column("group_urls", sa.JSON(), nullable=True))
    if not _has_column("manga", "scrape_layout"):
        op.add_column("manga", sa.Column("scrape_layout", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column("manga", "scrape_layout"):
        op.drop_column("manga", "scrape_layout")
    if _has_column("chapters", "group_urls"):
        op.drop_column("chapters", "group_urls")
    if _has_column("chapters", "pages_bytes"):
        op.drop_column("chapters", "pages_bytes")
    if _has_column("chapters", "source_pages"):
        op.drop_column("chapters", "source_pages")
