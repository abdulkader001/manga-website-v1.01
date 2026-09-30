"""Add permission_overrides table (SRS 1F.6)

Per-person permission overrides: one row per (user, permission) with
state granted|revoked. Absence of a row means inherited (role default).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260710_permission_overrides"
down_revision = "20260705_email_verified"
branch_labels = None
depends_on = None

TABLE = "permission_overrides"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "permission", name="uq_permission_override"),
    )
    op.create_index("ix_permission_overrides_user_id", TABLE, ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_index("ix_permission_overrides_user_id", table_name=TABLE)
        op.drop_table(TABLE)
