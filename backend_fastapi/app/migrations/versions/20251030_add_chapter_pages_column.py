"""Add pages column to chapters"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251030_add_chapter_pages_column"
down_revision = "20251025_add_manga_created_at"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("chapters"):
        return

    op.add_column("chapters", sa.Column("pages", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("chapters"):
        return
    op.drop_column("chapters", "pages")
