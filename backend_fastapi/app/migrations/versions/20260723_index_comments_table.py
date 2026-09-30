"""Index comments on (target_type, target_id, parent_id) and parent_id (SRS 4A.3)

``comments`` is a high-volume table (Part 4A.1: "Comments, reactions,
reputation | Community | High volume"). Every thread listing filters by
``target_type``/``target_id``/``parent_id is NULL`` (top-level comments) and
every reply fetch filters by ``parent_id IN (...)`` (comment_service.list_thread).

``20260722_native_comments_core`` indexed ``(target_type, target_id)`` but not
``parent_id``, so the reply-fetch BFS degrades to a full table scan as comments
accumulate. This replaces that 2-column index with a 3-column one covering the
listing query (a leading-column subset, so it serves the same lookups) and
adds the missing ``parent_id`` index — rather than keeping both, which would
just tax every write for no read benefit (SRS 4A.3: unused/redundant indexes
cost write performance).
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260723_index_comments_table"
down_revision = "20260722_reputation_ranking_pills"
branch_labels = None
depends_on = None

TABLE = "comments"


def _existing_indexes(inspector) -> set[str]:
    if not inspector.has_table(TABLE):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing = _existing_indexes(inspector)
    if "ix_comments_target_parent" not in existing:
        op.create_index(
            "ix_comments_target_parent",
            TABLE,
            ["target_type", "target_id", "parent_id"],
        )
    if "ix_comments_parent_id" not in existing:
        op.create_index("ix_comments_parent_id", TABLE, ["parent_id"])
    if "ix_comments_target" in existing:
        op.drop_index("ix_comments_target", table_name=TABLE)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = _existing_indexes(inspector)
    if "ix_comments_target" not in existing:
        op.create_index("ix_comments_target", TABLE, ["target_type", "target_id"])
    if "ix_comments_parent_id" in existing:
        op.drop_index("ix_comments_parent_id", table_name=TABLE)
    if "ix_comments_target_parent" in existing:
        op.drop_index("ix_comments_target_parent", table_name=TABLE)
