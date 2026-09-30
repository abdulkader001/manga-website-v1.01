"""Add default NOW() to users.updated_at and backfill existing NULLs"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251019_fix_updated_at_default"
down_revision = "20251019_add_updated_at_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL;"
        )
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "updated_at",
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
    else:
        op.execute("UPDATE users SET updated_at = NOW() WHERE updated_at IS NULL;")
        op.execute("ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT NOW();")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "updated_at",
                server_default=None,
            )
    else:
        op.execute("ALTER TABLE users ALTER COLUMN updated_at DROP DEFAULT;")
