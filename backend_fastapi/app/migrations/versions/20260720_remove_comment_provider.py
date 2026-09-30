"""Remove the third-party comment-provider system (SRS 1F.12 / Req 20)

Comments are native. Drops the comment_provider_setting table and its stored
provider selection/credentials. Reversible (downgrade recreates an empty table).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260720_remove_comment_provider"
down_revision = "20260715_moderator_role"
branch_labels = None
depends_on = None

TABLE = "comment_provider_setting"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "provider",
                sa.String(length=50),
                nullable=False,
                server_default="internal",
            ),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
