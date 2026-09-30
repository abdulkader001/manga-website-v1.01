"""Align users and user_api_keys tables with current models"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError

revision = "20251105_update_user_auth_schema"
down_revision = "d9d80c5ffdd8"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    try:
        return any(
            col["name"] == column_name for col in inspector.get_columns(table_name)
        )
    except NoSuchTableError:
        return False


def _add_user_column(inspector, column_name, column):
    if not _has_column(inspector, "users", column_name):
        op.add_column("users", column)


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    _add_user_column(
        inspector,
        "name",
        sa.Column("name", sa.String(length=150), nullable=True),
    )
    _add_user_column(
        inspector,
        "profile_image",
        sa.Column("profile_image", sa.String(length=500), nullable=True),
    )
    _add_user_column(
        inspector,
        "refresh_token",
        sa.Column("refresh_token", sa.String(length=255), nullable=True),
    )
    _add_user_column(
        inspector,
        "access_token",
        sa.Column("access_token", sa.String(length=255), nullable=True),
    )

    if inspector.has_table("user_api_keys"):
        metadata = sa.MetaData()

        old_table = sa.Table(
            "user_api_keys",
            metadata,
            sa.Column("id", sa.Integer),
            sa.Column("user_id", sa.Integer),
            sa.Column("ocr_api", sa.String(length=255)),
            sa.Column("translation_api", sa.String(length=255)),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

        new_table = op.create_table(
            "user_api_keys_new",
            sa.Column("id", sa.Integer, primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("api_key", sa.String(length=255), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "user_id", "provider", name="uq_user_api_keys_user_provider"
            ),
        )

        connection = op.get_bind()
        rows = connection.execute(sa.select(old_table)).all()

        insert_stmt = sa.insert(new_table)

        for row in rows:
            mapping = row._mapping
            created_at = mapping.get("created_at")
            updated_at = mapping.get("updated_at")
            if mapping.get("ocr_api"):
                connection.execute(
                    insert_stmt,
                    {
                        "user_id": mapping.get("user_id"),
                        "provider": "ocr",
                        "api_key": mapping.get("ocr_api"),
                        "config": {"provider_id": "custom"},
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )
            if mapping.get("translation_api"):
                connection.execute(
                    insert_stmt,
                    {
                        "user_id": mapping.get("user_id"),
                        "provider": "translation",
                        "api_key": mapping.get("translation_api"),
                        "config": {"provider_id": "custom"},
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )

        op.drop_table("user_api_keys")
        op.rename_table("user_api_keys_new", "user_api_keys")


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("user_api_keys"):
        metadata = sa.MetaData()
        current_table = sa.Table(
            "user_api_keys",
            metadata,
            sa.Column("id", sa.Integer),
            sa.Column("user_id", sa.Integer),
            sa.Column("provider", sa.String(length=100)),
            sa.Column("api_key", sa.String(length=255)),
            sa.Column("config", sa.JSON()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

        legacy_table = op.create_table(
            "user_api_keys_legacy",
            sa.Column("id", sa.Integer, primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("ocr_api", sa.String(length=255), nullable=True),
            sa.Column("translation_api", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
                nullable=False,
            ),
        )

        connection = op.get_bind()
        rows = connection.execute(sa.select(current_table)).all()

        # Build a map keyed by user_id to merge providers back into single row.
        merged = {}
        for row in rows:
            entry = merged.setdefault(
                row._mapping.get("user_id"),
                {
                    "ocr_api": None,
                    "translation_api": None,
                    "created_at": row._mapping.get("created_at"),
                    "updated_at": row._mapping.get("updated_at"),
                },
            )
            provider = row._mapping.get("provider")
            api_key = row._mapping.get("api_key")
            if provider == "ocr" and api_key:
                entry["ocr_api"] = api_key
            elif provider == "translation" and api_key:
                entry["translation_api"] = api_key

        insert_stmt = sa.insert(legacy_table)
        for user_id, payload in merged.items():
            connection.execute(
                insert_stmt,
                {
                    "user_id": user_id,
                    "ocr_api": payload["ocr_api"],
                    "translation_api": payload["translation_api"],
                    "created_at": payload["created_at"],
                    "updated_at": payload["updated_at"],
                },
            )

        op.drop_table("user_api_keys")
        op.rename_table("user_api_keys_legacy", "user_api_keys")

    for column in ("access_token", "refresh_token", "profile_image", "name"):
        if inspector.has_column("users", column):
            op.drop_column("users", column)
