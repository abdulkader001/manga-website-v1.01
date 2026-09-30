"""Remove custom-page creation (SRS 1F.12 / Req 20)

Custom page creation is no longer a feature. Drops the custom_pages table (and
the custom_page_visibility enum on Postgres). Reversible.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260725_remove_custom_pages"
down_revision = "20260720_remove_comment_provider"
branch_labels = None
depends_on = None

TABLE = "custom_pages"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS custom_page_visibility")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "visibility",
                sa.String(length=32),
                nullable=False,
                server_default="public",
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
