"""Merge heads before Part 2 (processing pipeline)

Three branches had drifted apart: the legacy provider_credentials chain
(20251223_add_enabled_column_to_provider_credentials), the older admin-audit
merge point (4be0d9f7edb6), and the current mainline
(20260811_notification_system, itself downstream of 1H.14's
20260810_ocr_translation_cache). This merge gives Part 2's migrations a
single parent, same pattern as the three merge migrations already in this
history (d9d80c5ffdd8, 4be0d9f7edb6, 20251019_merge_heads_fix_chain).
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260812_merge_heads_before_part2"
down_revision = (
    "20251223_add_enabled_column_to_provider_credentials",
    "20260811_notification_system",
    "4be0d9f7edb6",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector
    # Merge point only; no schema operations.


def downgrade() -> None:
    pass
