"""Create comments table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250925_create_comments_table"
down_revision = "20250925_add_comments_provider_setting"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.drop_table("comments")
