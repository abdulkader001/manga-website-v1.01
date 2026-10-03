"""Deleting a series removes what points at it (reading history, bookmarks,
OCR / translation caches) instead of failing.

Before this, eight foreign keys pointing at ``manga`` / ``chapters`` /
``ocr_cache`` had no delete rule, so on PostgreSQL deleting any series that a
signed-in reader had opened, or whose pages had been translated, failed with
HTTP 500 (plan.md P0-3). Rows that only describe the series go with it
(``CASCADE``); scraping-job history and a translation's link to its OCR row
are kept with the link emptied (``SET NULL``, both columns are nullable).

PostgreSQL only: SQLite cannot alter a foreign key in place and the test
databases are built from the models, which carry the same rules.

Downgrade restores the old rule (``NO ACTION``); no data is lost either way.

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

# (table, column, referenced table, rule after upgrade)
KEYS = [
    ("bookmarks", "chapter_id", "chapters", "CASCADE"),
    ("bookmarks", "manga_id", "manga", "CASCADE"),
    ("read_history", "chapter_id", "chapters", "CASCADE"),
    ("read_history", "manga_id", "manga", "CASCADE"),
    ("ocr_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "ocr_cache_id", "ocr_cache", "SET NULL"),
    ("scraping_jobs", "manga_id", "manga", "SET NULL"),
]


def _existing_name(inspector, table: str, column: str, referred: str):
    for fk in inspector.get_foreign_keys(table):
        if fk.get("referred_table") == referred and fk.get("constrained_columns") == [column]:
            return fk.get("name")
    return None


def _apply(rule_for) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table, column, referred, rule in KEYS:
        if not inspector.has_table(table) or not inspector.has_table(referred):
            continue
        name = f"fk_{table}_{column}_{referred}"
        current = _existing_name(inspector, table, column, referred)
        if current:
            op.drop_constraint(current, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred, [column], ["id"], ondelete=rule_for(rule))


def upgrade() -> None:
    _apply(lambda rule: rule)


def downgrade() -> None:
    _apply(lambda rule: None)
