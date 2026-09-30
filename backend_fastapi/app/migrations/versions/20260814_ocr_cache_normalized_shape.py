"""Extend ocr_cache/translation_cache for 2B.6 + 2C.1 + 2A.3

Additive, nullable columns only -- existing rows (text_boxes/
translated_boxes) keep working unchanged; new writes populate the richer
``regions`` shape alongside them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260814_ocr_cache_normalized_shape"
down_revision = "20260813_part2_processing_settings_providers"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    ocr_cols = _columns(inspector, "ocr_cache")
    if ocr_cols:
        additions = [
            ("regions", sa.JSON()),
            ("detected_language", sa.String(16)),
            ("detected_script", sa.String(24)),
            ("reading_order_mode", sa.String(24)),
            ("engine_tier", sa.Integer()),
            ("page_width", sa.Integer()),
            ("page_height", sa.Integer()),
            ("ai_assisted_regions", sa.JSON()),
        ]
        for name, coltype in additions:
            if name not in ocr_cols:
                op.add_column("ocr_cache", sa.Column(name, coltype, nullable=True))

    tc_cols = _columns(inspector, "translation_cache")
    if tc_cols:
        if "regions" not in tc_cols:
            op.add_column(
                "translation_cache", sa.Column("regions", sa.JSON(), nullable=True)
            )
        if "ai_assisted_regions" not in tc_cols:
            op.add_column(
                "translation_cache",
                sa.Column("ai_assisted_regions", sa.JSON(), nullable=True),
            )
        if "contributed_by_sharing" not in tc_cols:
            op.add_column(
                "translation_cache",
                sa.Column(
                    "contributed_by_sharing",
                    sa.Boolean(),
                    nullable=False,
                    server_default="false",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tc_cols = _columns(inspector, "translation_cache")
    for name in ("contributed_by_sharing", "ai_assisted_regions", "regions"):
        if name in tc_cols:
            op.drop_column("translation_cache", name)

    ocr_cols = _columns(inspector, "ocr_cache")
    for name in (
        "ai_assisted_regions",
        "page_height",
        "page_width",
        "engine_tier",
        "reading_order_mode",
        "detected_script",
        "detected_language",
        "regions",
    ):
        if name in ocr_cols:
            op.drop_column("ocr_cache", name)
