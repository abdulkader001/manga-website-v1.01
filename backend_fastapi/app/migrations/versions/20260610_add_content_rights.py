"""Add content-rights columns to manga and approved_source_domains (SRS 1J)

``may_host`` and ``may_translate`` are separate permissions on both the series
(``manga``) and the source website (``approved_source_domains``). Existing rows
default to open (True) so nothing already ingested is retroactively blocked.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260610_add_content_rights"
down_revision = "20260510_add_manga_title_trgm_index"
branch_labels = None
depends_on = None


def _columns(inspector, table):
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    manga_cols = _columns(inspector, "manga")
    if "manga" in inspector.get_table_names():
        if "may_host" not in manga_cols:
            op.add_column(
                "manga",
                sa.Column(
                    "may_host",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if "may_translate" not in manga_cols:
            op.add_column(
                "manga",
                sa.Column(
                    "may_translate",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if "attribution" not in manga_cols:
            op.add_column(
                "manga", sa.Column("attribution", sa.String(length=512), nullable=True)
            )
        if "rights_note" not in manga_cols:
            op.add_column("manga", sa.Column("rights_note", sa.Text(), nullable=True))
        if "takedown_status" not in manga_cols:
            op.add_column(
                "manga",
                sa.Column(
                    "takedown_status",
                    sa.String(length=32),
                    nullable=False,
                    server_default="none",
                ),
            )
        if "takedown_reason" not in manga_cols:
            op.add_column(
                "manga", sa.Column("takedown_reason", sa.Text(), nullable=True)
            )

    domain_cols = _columns(inspector, "approved_source_domains")
    if "approved_source_domains" in inspector.get_table_names():
        if "may_host" not in domain_cols:
            op.add_column(
                "approved_source_domains",
                sa.Column(
                    "may_host",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if "may_translate" not in domain_cols:
            op.add_column(
                "approved_source_domains",
                sa.Column(
                    "may_translate",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if "attribution" not in domain_cols:
            op.add_column(
                "approved_source_domains",
                sa.Column("attribution", sa.String(length=512), nullable=True),
            )
        if "license" not in domain_cols:
            op.add_column(
                "approved_source_domains",
                sa.Column("license", sa.String(length=128), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table, cols in (
        (
            "manga",
            [
                "takedown_reason",
                "takedown_status",
                "rights_note",
                "attribution",
                "may_translate",
                "may_host",
            ],
        ),
        (
            "approved_source_domains",
            ["license", "attribution", "may_translate", "may_host"],
        ),
    ):
        existing = _columns(inspector, table)
        for col in cols:
            if col in existing:
                op.drop_column(table, col)
