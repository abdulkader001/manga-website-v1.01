"""Backfill missing tables and columns for schema verification."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "20251206_fill_schema_gaps"
down_revision = "20251205_create_secret_phrase_attempts"
branch_labels = None
depends_on = None


def _table_columns(inspector, table_name):
    return {col["name"] for col in inspector.get_columns(table_name)}


def create_unique_index_with_null_handling():
    """Ensure source_url is unique while allowing multiple NULLs on PG14."""

    conn = op.get_bind()
    dialect = conn.dialect.name

    op.execute("DROP INDEX IF EXISTS ix_scraping_jobs_source_url_unique;")

    if dialect != "postgresql":
        # Non-Postgres backends (e.g. SQLite tests) rely on a simple unique index
        # that naturally treats NULL values as distinct without extra syntax.
        op.create_index(
            "ix_scraping_jobs_source_url_unique",
            "scraping_jobs",
            ["source_url"],
            unique=True,
        )
        return

    op.execute(
        "ALTER TABLE scraping_jobs DROP CONSTRAINT IF EXISTS uq_scraping_jobs_source_url;"
    )

    vnum = int(conn.execute(text("SHOW server_version_num")).scalar())
    if vnum >= 150000:
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_scraping_jobs_source_url_unique
            ON scraping_jobs (source_url) NULLS NOT DISTINCT;
            """
        )
    else:
        # Postgres 14 lacks NULLS NOT DISTINCT, so we emulate "unique when NOT NULL"
        # with a partial unique index instead.
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_scraping_jobs_source_url_unique
            ON scraping_jobs (source_url)
            WHERE source_url IS NOT NULL;
            """
        )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if bind.dialect.name == "sqlite":
        # SQLite deployments rely on SQLAlchemy metadata sync rather than
        # complex alter-table migrations. Skip the schema gap filler to avoid
        # unsupported operations during testing.
        return

    if not inspector.has_table("settings"):
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=100), nullable=False, unique=True),
            sa.Column("value", sa.Text(), nullable=True),
        )

    if not inspector.has_table("footer_settings"):
        op.create_table(
            "footer_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("contact", sa.Text(), nullable=True),
            sa.Column("terms", sa.Text(), nullable=True),
            sa.Column("privacy", sa.Text(), nullable=True),
            sa.Column("socials", sa.JSON(), nullable=True),
        )

    if not inspector.has_table("comment_provider_setting"):
        op.create_table(
            "comment_provider_setting",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "provider",
                sa.String(length=50),
                nullable=False,
                server_default="internal",
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not inspector.has_table("custom_pages"):
        visibility_enum = sa.Enum(
            "public",
            "authenticated",
            "secondary_admin",
            "admin",
            "permanent_admin",
            name="custom_page_visibility",
            create_type=False,
        )
        if bind.dialect.name == "postgresql":
            visibility_enum.create(bind, checkfirst=True)
        visibility_type = sa.String(length=32)

        columns = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "visibility",
                visibility_type,
                nullable=False,
                server_default="'public'",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ]
        op.create_table("custom_pages", *columns)

    if not inspector.has_table("custom_tabs"):
        op.create_table(
            "custom_tabs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("url", sa.String(length=255), nullable=False),
            sa.Column(
                "is_global",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not inspector.has_table("complaints"):
        op.create_table(
            "complaints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not inspector.has_table("login_tokens"):
        op.create_table(
            "login_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("token", sa.String(length=255), nullable=False, unique=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_login_tokens_token", "login_tokens", ["token"], unique=True)

    # Column additions
    if inspector.has_table("bookmarks"):
        columns = _table_columns(inspector, "bookmarks")
        if "created_at" not in columns:
            with op.batch_alter_table("bookmarks", recreate="always") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "created_at",
                        sa.DateTime(),
                        nullable=False,
                        server_default=sa.func.now(),
                    )
                )

    if inspector.has_table("read_history"):
        columns = _table_columns(inspector, "read_history")
        if "last_read_at" not in columns:
            with op.batch_alter_table("read_history", recreate="always") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "last_read_at",
                        sa.DateTime(),
                        nullable=False,
                        server_default=sa.func.now(),
                    )
                )
            op.create_index(
                "ix_read_history_user_id_last_read_at",
                "read_history",
                ["user_id", "last_read_at"],
            )

    if inspector.has_table("sources"):
        columns = _table_columns(inspector, "sources")
        missing_defs = []
        if "provider" not in columns:
            missing_defs.append(
                sa.Column("provider", sa.String(length=100), nullable=True)
            )
        if "schedule" not in columns:
            missing_defs.append(
                sa.Column("schedule", sa.String(length=50), nullable=True)
            )
        if "created_at" not in columns:
            missing_defs.append(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
        if "updated_at" not in columns:
            missing_defs.append(
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )

        fk_name = "fk_scraping_jobs_source_id_sources"
        fk_dropped = False
        if missing_defs and inspector.has_table("scraping_jobs"):
            for fk in inspector.get_foreign_keys("scraping_jobs"):
                if fk.get("name") == fk_name:
                    op.drop_constraint(fk_name, "scraping_jobs", type_="foreignkey")
                    fk_dropped = True
                    break

        if missing_defs:
            with op.batch_alter_table("sources", recreate="always") as batch_op:
                for column in missing_defs:
                    batch_op.add_column(column)

        if fk_dropped:
            op.create_foreign_key(
                fk_name,
                "scraping_jobs",
                "sources",
                ["source_id"],
                ["id"],
            )

    if inspector.has_table("scraping_jobs"):
        columns = _table_columns(inspector, "scraping_jobs")
        if "manga_id" not in columns:
            with op.batch_alter_table("scraping_jobs", recreate="always") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "manga_id",
                        sa.Integer(),
                        sa.ForeignKey("manga.id"),
                        nullable=True,
                    )
                )
        create_unique_index_with_null_handling()

    if inspector.has_table("social_links"):
        columns = _table_columns(inspector, "social_links")
        missing = []
        if "created_at" not in columns:
            missing.append(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
        if "updated_at" not in columns:
            missing.append(
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
        if missing:
            with op.batch_alter_table("social_links", recreate="always") as batch_op:
                for column in missing:
                    batch_op.add_column(column)

    if inspector.has_table("provider_credentials"):
        columns = _table_columns(inspector, "provider_credentials")
        if "provider_name" not in columns:
            with op.batch_alter_table(
                "provider_credentials", recreate="always"
            ) as batch_op:
                batch_op.add_column(
                    sa.Column("provider_name", sa.String(length=100), nullable=True)
                )
            op.execute(
                sa.text("UPDATE provider_credentials SET provider_name = 'default'")
            )
            with op.batch_alter_table(
                "provider_credentials", recreate="always"
            ) as batch_op:
                batch_op.alter_column(
                    "provider_name",
                    existing_type=sa.String(length=100),
                    nullable=False,
                )

    if inspector.has_table("copyright_bindings"):
        columns = _table_columns(inspector, "copyright_bindings")
        additions = []
        if "manga_title" not in columns:
            additions.append(
                sa.Column("manga_title", sa.String(length=255), nullable=True)
            )
        if "proof_url" not in columns:
            additions.append(
                sa.Column("proof_url", sa.String(length=500), nullable=True)
            )
        if additions:
            with op.batch_alter_table(
                "copyright_bindings", recreate="always"
            ) as batch_op:
                for column in additions:
                    batch_op.add_column(column)


def downgrade():
    # This migration backfills missing schema elements; downgrade drops newly created objects.
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("scraping_jobs"):
        op.execute("DROP INDEX IF EXISTS ix_scraping_jobs_source_url_unique;")
        if bind.dialect.name == "postgresql":
            op.execute(
                "ALTER TABLE scraping_jobs DROP CONSTRAINT IF EXISTS uq_scraping_jobs_source_url;"
            )

    if inspector.has_index("login_tokens", "ix_login_tokens_token"):
        op.drop_index("ix_login_tokens_token", table_name="login_tokens")

    for table_name in (
        "login_tokens",
        "complaints",
        "custom_tabs",
        "custom_pages",
        "comment_provider_setting",
        "footer_settings",
        "settings",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    for table_name, column_name in (
        ("copyright_bindings", "proof_url"),
        ("copyright_bindings", "manga_title"),
        ("provider_credentials", "provider_name"),
        ("social_links", "updated_at"),
        ("social_links", "created_at"),
        ("scraping_jobs", "manga_id"),
        ("sources", "updated_at"),
        ("sources", "created_at"),
        ("sources", "schedule"),
        ("sources", "provider"),
        ("read_history", "last_read_at"),
        ("bookmarks", "created_at"),
    ):
        if inspector.has_table(table_name):
            columns = _table_columns(inspector, table_name)
            if column_name in columns:
                with op.batch_alter_table(table_name, recreate="always") as batch_op:
                    batch_op.drop_column(column_name)

    if bind.dialect.name != "sqlite":
        op.execute("DROP TYPE IF EXISTS custom_page_visibility")
