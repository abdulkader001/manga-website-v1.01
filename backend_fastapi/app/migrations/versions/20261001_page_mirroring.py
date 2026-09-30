"""Chapter page mirroring: keep source URLs and stored size next to the pages.

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


def downgrade() -> None:
    if _has_column("chapters", "pages_bytes"):
        op.drop_column("chapters", "pages_bytes")
    if _has_column("chapters", "source_pages"):
        op.drop_column("chapters", "source_pages")
