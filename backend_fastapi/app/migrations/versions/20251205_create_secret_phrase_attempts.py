"""Create secret_phrase_attempts audit table."""

from alembic import op
import sqlalchemy as sa

revision = "20251205_create_secret_phrase_attempts"
down_revision = "20251201_add_admin_bootstrap_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_phrase_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_secret_phrase_attempts_user_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_secret_phrase_attempts_user_id_created_at",
        "secret_phrase_attempts",
        ["user_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_secret_phrase_attempts_user_id_created_at",
        table_name="secret_phrase_attempts",
    )
    op.drop_table("secret_phrase_attempts")
