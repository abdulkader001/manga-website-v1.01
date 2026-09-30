"""Series management & website governance data model (SRS 1G.1)

- approved_source_domains: website lifecycle (status, approver, languages,
  request rate limit, health check timestamp)
- manga: series record fields (original title, alt titles, authors, artists,
  submitter, ingestion status, last error)
- chapters: ingestion_status
- parser_versions: versioned parser definitions per website (1G.8.5)
- notifications: bell-notification store for 1G events (1I delivers them)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260805_series_governance"
down_revision = "20260730_permission_presets"
branch_labels = None
depends_on = None


def _add_column(inspector, table: str, column: sa.Column) -> None:
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("approved_source_domains"):
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        )
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("original_languages", sa.JSON(), nullable=True),
        )
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("approved_by", sa.Integer(), nullable=True),
        )
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("approved_at", sa.DateTime(), nullable=True),
        )
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("request_rate_limit", sa.Integer(), nullable=True),
        )
        _add_column(
            inspector,
            "approved_source_domains",
            sa.Column("last_health_check", sa.DateTime(), nullable=True),
        )

    if inspector.has_table("manga"):
        _add_column(inspector, "manga", sa.Column("original_title", sa.String()))
        _add_column(
            inspector,
            "manga",
            sa.Column("alternative_titles", sa.JSON(), nullable=True),
        )
        _add_column(inspector, "manga", sa.Column("authors", sa.JSON(), nullable=True))
        _add_column(inspector, "manga", sa.Column("artists", sa.JSON(), nullable=True))
        _add_column(
            inspector, "manga", sa.Column("added_by", sa.Integer(), nullable=True)
        )
        _add_column(
            inspector,
            "manga",
            sa.Column(
                "ingestion_status",
                sa.String(16),
                nullable=False,
                server_default="complete",
            ),
        )
        _add_column(
            inspector, "manga", sa.Column("last_error", sa.Text(), nullable=True)
        )

    if inspector.has_table("chapters"):
        _add_column(
            inspector,
            "chapters",
            sa.Column(
                "ingestion_status",
                sa.String(16),
                nullable=False,
                server_default="queued",
            ),
        )
        # Chapters that already have pages were ingested successfully.
        op.execute(
            "UPDATE chapters SET ingestion_status = 'complete' "
            "WHERE pages IS NOT NULL"
        )

    if not inspector.has_table("parser_versions"):
        op.create_table(
            "parser_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="candidate",
            ),
            sa.Column(
                "source", sa.String(length=16), nullable=False, server_default="manual"
            ),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("test_results", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "domain", "version", name="uq_parser_versions_domain_version"
            ),
        )
        op.create_index(
            "ix_parser_versions_domain_status",
            "parser_versions",
            ["domain", "status"],
        )

    if not inspector.has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("type", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column(
                "read", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "ix_notifications_user_read", "notifications", ["user_id", "read"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("notifications"):
        op.drop_table("notifications")
    if inspector.has_table("parser_versions"):
        op.drop_table("parser_versions")

    def _drop(table: str, names: list[str]) -> None:
        if not inspector.has_table(table):
            return
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name in names:
            if name in existing:
                op.drop_column(table, name)

    _drop("chapters", ["ingestion_status"])
    _drop(
        "manga",
        [
            "original_title",
            "alternative_titles",
            "authors",
            "artists",
            "added_by",
            "ingestion_status",
            "last_error",
        ],
    )
    _drop(
        "approved_source_domains",
        [
            "status",
            "original_languages",
            "approved_by",
            "approved_at",
            "request_rate_limit",
            "last_health_check",
        ],
    )
