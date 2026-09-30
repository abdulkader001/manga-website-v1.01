"""Add parser_type to sources"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20250911_add_parser_type_to_source"
down_revision = "20250910_add_unique_scrapingjob_url"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    if not inspector.has_table(table_name):
        return False

    return any(
        column["name"] == column_name for column in inspector.get_columns(table_name)
    )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "sources", "parser_type"):
        op.add_column(
            "sources", sa.Column("parser_type", sa.String(100), nullable=True)
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "sources", "parser_type"):
        op.drop_column("sources", "parser_type")
