"""Create copyright_bindings table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250912_add_copyright_bindings_table"
down_revision = "20250911_add_parser_type_to_source"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.create_table(
        "copyright_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("phrase_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector
    op.drop_table("copyright_bindings")
