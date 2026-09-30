"""add updated_at column to users

Revision ID: 20251019_add_updated_at_to_users
Revises: 1307b999f755
Create Date: 2024-07-08 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251019_add_updated_at_to_users"
down_revision = "1307b999f755"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
        )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL;"
        )
    else:
        op.execute("UPDATE users SET updated_at = NOW() WHERE updated_at IS NULL;")

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("updated_at", nullable=False)


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("updated_at")
