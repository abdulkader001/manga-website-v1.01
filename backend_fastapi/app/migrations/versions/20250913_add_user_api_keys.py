"""Create user_api_keys table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250913_add_user_api_keys"
down_revision = "20250912_add_copyright_bindings_table"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "user_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("ocr_api", sa.String(length=255), nullable=True),
        sa.Column("translation_api", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector
    op.drop_table("user_api_keys")
