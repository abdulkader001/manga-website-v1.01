"""Deleting a series also removes what points at it (plan.md P0-3).

On PostgreSQL, deleting a series, "delete all manga", bulk delete and "purge
all images" failed with HTTP 500 as soon as a reader had opened a chapter or
a page had been translated: these foreign keys had no delete rule, so the
database refused to remove the chapter or series they pointed at.

Reading history, chapter bookmarks and the OCR/translation caches of a
deleted chapter or series are now removed with it (ON DELETE CASCADE). A
translation keeps its row when its OCR row goes, and a scraping job keeps
its row when its series goes (ON DELETE SET NULL; both columns are
nullable).

PostgreSQL only: SQLite builds its schema from the models, which carry the
same rules. Constraints are found by their columns, not their names, so a
database whose names differ is handled too.

Downgrade puts the rules back to NO ACTION. No data is lost by either step.

Revision ID: 20261018_cascade_series_children
Revises: 20261017_login_required_default_off
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261018_cascade_series_children"
down_revision = "20261017_login_required_default_off"
branch_labels = None
depends_on = None

# (table, column, referenced table, rule after the upgrade)
FOREIGN_KEYS = (
    ("bookmarks", "chapter_id", "chapters", "CASCADE"),
    ("bookmarks", "manga_id", "manga", "CASCADE"),
    ("read_history", "chapter_id", "chapters", "CASCADE"),
    ("read_history", "manga_id", "manga", "CASCADE"),
    ("ocr_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "ocr_cache_id", "ocr_cache", "SET NULL"),
    ("scraping_jobs", "manga_id", "manga", "SET NULL"),
)


def _replace(ondelete_for) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table, column, referred, rule in FOREIGN_KEYS:
        if not inspector.has_table(table) or not inspector.has_table(referred):
            continue
        for fk in inspector.get_foreign_keys(table):
            if fk["constrained_columns"] == [column] and fk["referred_table"] == referred and fk["name"]:
                op.drop_constraint(fk["name"], table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_{column}_{referred}",
            table,
            referred,
            [column],
            ["id"],
            ondelete=ondelete_for(rule),
        )


def upgrade() -> None:
    _replace(lambda rule: rule)


def downgrade() -> None:
    _replace(lambda rule: None)
