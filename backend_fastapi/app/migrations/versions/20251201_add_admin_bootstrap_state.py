"""Create admin_bootstrap_state table"""

from alembic import op
import sqlalchemy as sa

revision = "20251201_add_admin_bootstrap_state"
down_revision = "20251105_update_user_auth_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_bootstrap_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_initialized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("initialized_at", sa.DateTime(), nullable=True),
        sa.Column("initialized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("secret_phrase_hash", sa.String(length=128), nullable=True),
        sa.Column("secret_phrase_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["initialized_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_admin_bootstrap_state_initialized_by",
        "admin_bootstrap_state",
        ["initialized_by_user_id"],
    )


def downgrade():
    op.drop_index(
        "ix_admin_bootstrap_state_initialized_by", table_name="admin_bootstrap_state"
    )
    op.drop_table("admin_bootstrap_state")
