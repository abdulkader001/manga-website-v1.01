"""Schema for the v1.01 reader UI: profile completion + password login,
catalogue stats, ratings, likes, chapter reports, announcements.

Revision ID: 20260930_reader_ui_integration
Revises: 20260903_token_revocation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260930_reader_ui_integration"
down_revision = "20260903_token_revocation"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {col["name"] for col in _inspector().get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # MangaUpdates (and the UI) describe finished series as "completed".
        # The migration chain created manga.status as VARCHAR; only databases
        # built from ORM metadata carry a native enum that needs the value.
        has_enum = bind.execute(
            sa.text("SELECT 1 FROM pg_type WHERE typname = 'manga_status'")
        ).first()
        if has_enum:
            op.execute("ALTER TYPE manga_status ADD VALUE IF NOT EXISTS 'completed'")

    # ----- users -----------------------------------------------------------
    _add_column("users", sa.Column("microsoft_sub", sa.String(255), nullable=True))
    _add_column("users", sa.Column("birth_date", sa.Date(), nullable=True))
    _add_column("users", sa.Column("gender", sa.String(32), nullable=True))
    _add_column(
        "users",
        sa.Column(
            "profile_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    _add_column(
        "users",
        sa.Column(
            "failed_login_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    _add_column("users", sa.Column("login_locked_until", sa.DateTime(), nullable=True))
    if _has_column("users", "microsoft_sub"):
        # A unique index (not ALTER ... ADD CONSTRAINT) so SQLite can run this too.
        existing = {ix["name"] for ix in _inspector().get_indexes("users")}
        if "uq_users_microsoft_sub" not in existing:
            op.create_index(
                "uq_users_microsoft_sub", "users", ["microsoft_sub"], unique=True
            )

    # ----- manga / chapters --------------------------------------------------
    _add_column("manga", sa.Column("mangaupdates_url", sa.String(512), nullable=True))
    _add_column(
        "manga",
        sa.Column("is_hot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column(
        "manga",
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
    )
    _add_column(
        "manga",
        sa.Column(
            "auto_scrape_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    _add_column(
        "chapters",
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column(
        "chapters",
        sa.Column(
            "created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()
        ),
    )

    _add_column("scraping_jobs", sa.Column("options", sa.JSON(), nullable=True))

    # ----- engagement tables -------------------------------------------------
    if not _has_table("manga_ratings"):
        op.create_table(
            "manga_ratings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "manga_id",
                sa.Integer(),
                sa.ForeignKey("manga.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("score", sa.SmallInteger(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "manga_id", "user_id", name="uq_manga_ratings_manga_user"
            ),
            sa.CheckConstraint(
                "score >= 1 AND score <= 10", name="ck_manga_ratings_score"
            ),
        )
        op.create_index("ix_manga_ratings_manga_id", "manga_ratings", ["manga_id"])

    if not _has_table("chapter_likes"):
        op.create_table(
            "chapter_likes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint(
                "chapter_id", "user_id", name="uq_chapter_likes_chapter_user"
            ),
        )
        op.create_index("ix_chapter_likes_chapter_id", "chapter_likes", ["chapter_id"])

    if not _has_table("chapter_reports"):
        op.create_table(
            "chapter_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "manga_id",
                sa.Integer(),
                sa.ForeignKey("manga.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("report_type", sa.String(64), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column(
                "resolved_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
        )
        op.create_index(
            "ix_chapter_reports_chapter_id", "chapter_reports", ["chapter_id"]
        )
        op.create_index(
            "ix_chapter_reports_status_created",
            "chapter_reports",
            ["status", "created_at"],
        )

    if not _has_table("announcements"):
        op.create_table(
            "announcements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("type", sa.String(32), nullable=False, server_default="info"),
            sa.Column("is_popup", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
        )

    if not _has_table("admin_task_results"):
        op.create_table(
            "admin_task_results",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column(
                "requested_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "ix_admin_task_results_requested_by", "admin_task_results", ["requested_by"]
        )
        op.create_index(
            "ix_admin_task_results_created_at", "admin_task_results", ["created_at"]
        )

    if not _has_table("manga_daily_views"):
        op.create_table(
            "manga_daily_views",
            sa.Column(
                "manga_id",
                sa.Integer(),
                sa.ForeignKey("manga.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("day", sa.Date(), primary_key=True),
            sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for table in (
        "admin_task_results",
        "manga_daily_views",
        "announcements",
        "chapter_reports",
        "chapter_likes",
        "manga_ratings",
    ):
        if _has_table(table):
            op.drop_table(table)

    for table, column in (
        ("scraping_jobs", "options"),
        ("chapters", "created_at"),
        ("chapters", "views"),
        ("manga", "auto_scrape_enabled"),
        ("manga", "views"),
        ("manga", "is_hot"),
        ("manga", "mangaupdates_url"),
        ("users", "login_locked_until"),
        ("users", "failed_login_count"),
        ("users", "password_hash"),
        ("users", "profile_completed"),
        ("users", "gender"),
        ("users", "birth_date"),
    ):
        if _has_column(table, column):
            op.drop_column(table, column)
    if _has_column("users", "microsoft_sub"):
        existing = {ix["name"] for ix in _inspector().get_indexes("users")}
        if "uq_users_microsoft_sub" in existing:
            op.drop_index("uq_users_microsoft_sub", table_name="users")
        op.drop_column("users", "microsoft_sub")
    # Postgres cannot drop an enum value; 'completed' stays in manga_status.
