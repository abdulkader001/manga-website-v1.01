"""Add text_hash + quality_score to ocr_cache and translation_cache

Backing columns for the content-based write authority in
``submission_quality_gate``: ``text_hash`` recognises an identical
resubmission without comparing text, ``quality_score`` records the 0-100
fidelity/coherence score an entry was last judged on so a later submission
has a baseline to beat.

Additive and nullable throughout -- existing rows keep working unchanged
and are simply treated as "never hashed / never scored" until the next
write passes through the gate.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260901_cache_quality_gate"
down_revision = "20260831_ad_slot_placement"
branch_labels = None
depends_on = None

_TABLES = ("ocr_cache", "translation_cache")
_COLUMNS = (
    ("text_hash", sa.String(64)),
    ("quality_score", sa.Float()),
)


def _columns(inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in _TABLES:
        existing = _columns(inspector, table)
        if not existing:
            continue
        for name, coltype in _COLUMNS:
            if name not in existing:
                op.add_column(table, sa.Column(name, coltype, nullable=True))

        index_name = f"ix_{table}_text_hash"
        if index_name not in _indexes(inspector, table):
            op.create_index(index_name, table, ["text_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table in _TABLES:
        existing = _columns(inspector, table)
        if not existing:
            continue

        index_name = f"ix_{table}_text_hash"
        if index_name in _indexes(inspector, table):
            op.drop_index(index_name, table_name=table)

        for name, _coltype in reversed(_COLUMNS):
            if name in existing:
                op.drop_column(table, name)
