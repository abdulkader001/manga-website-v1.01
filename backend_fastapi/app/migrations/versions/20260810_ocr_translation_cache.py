"""Shared OCR/translation cache tables (SRS 1H.14)

Two-layer split: ocr_cache (once per chapter page, language-independent)
and translation_cache (once per chapter page per target language), each
with a quality_tier for free->paid upgrades and a last_accessed_at column
for LRU eviction.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260810_ocr_translation_cache"
down_revision = "20260809_disposable_email_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ocr_cache"):
        op.create_table(
            "ocr_cache",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id"),
                nullable=False,
            ),
            sa.Column("page_index", sa.Integer(), nullable=False),
            sa.Column("text_boxes", sa.JSON(), nullable=False),
            sa.Column(
                "quality_tier",
                sa.String(16),
                nullable=False,
                server_default="free",
            ),
            sa.Column("provider", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "last_accessed_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "uq_ocr_cache_chapter_page",
            "ocr_cache",
            ["chapter_id", "page_index"],
            unique=True,
        )

    if not inspector.has_table("translation_cache"):
        op.create_table(
            "translation_cache",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id"),
                nullable=False,
            ),
            sa.Column("page_index", sa.Integer(), nullable=False),
            sa.Column("target_lang", sa.String(16), nullable=False),
            sa.Column(
                "ocr_cache_id",
                sa.Integer(),
                sa.ForeignKey("ocr_cache.id"),
                nullable=True,
            ),
            sa.Column("translated_boxes", sa.JSON(), nullable=False),
            sa.Column(
                "quality_tier",
                sa.String(16),
                nullable=False,
                server_default="free",
            ),
            sa.Column("provider", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "last_accessed_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "uq_translation_cache_chapter_page_lang",
            "translation_cache",
            ["chapter_id", "page_index", "target_lang"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("translation_cache"):
        op.drop_table("translation_cache")
    if inspector.has_table("ocr_cache"):
        op.drop_table("ocr_cache")
