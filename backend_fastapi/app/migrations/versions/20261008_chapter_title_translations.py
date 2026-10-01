"""Cache of translated chapter subtitles per reader language.

Revision ID: 20261008_chapter_title_translations
Revises: 20261007_three_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261008_chapter_title_translations"
down_revision = "20261007_three_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("chapters"):
        return
    if "title_translations" not in {c["name"] for c in inspector.get_columns("chapters")}:
        op.add_column("chapters", sa.Column("title_translations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chapters", "title_translations")
