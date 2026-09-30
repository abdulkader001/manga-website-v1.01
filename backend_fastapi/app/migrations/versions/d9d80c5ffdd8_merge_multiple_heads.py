"""Finalize migration chain"""

from alembic import op
from sqlalchemy import inspect

revision = "d9d80c5ffdd8"
down_revision = "20251030_add_chapter_pages_column"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    # This merge migration intentionally performs no operations.


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    # This merge migration intentionally performs no operations.
