"""Create approved_source_domains table."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20251220_add_approved_source_domains"
down_revision = "20251212_add_system_state_and_admin_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approved_source_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False, unique=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("approved_source_domains")
