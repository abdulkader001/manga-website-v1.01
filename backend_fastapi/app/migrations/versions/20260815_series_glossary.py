"""Per-series character-name glossary (SRS 2C.1)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260815_series_glossary"
down_revision = "20260814_ocr_cache_normalized_shape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("series_glossary_terms"):
        return
    op.create_table(
        "series_glossary_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "manga_id",
            sa.Integer(),
            sa.ForeignKey("manga.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_lang", sa.String(16), nullable=False),
        sa.Column("source_term", sa.String(120), nullable=False),
        sa.Column("translated_term", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_glossary_manga_lang_source",
        "series_glossary_terms",
        ["manga_id", "target_lang", "source_term"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("series_glossary_terms"):
        op.drop_table("series_glossary_terms")
