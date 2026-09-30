"""Enforce uniqueness for copyright phrase hashes"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "20251005_enforce_unique_phrase_hash"
down_revision = "20251001_extend_ad_slots_add_clicks"
branch_labels = None
depends_on = None


def create_version_aware_unique_index(table: str, column: str, index_name: str) -> None:
    """Create a unique index that handles NULL semantics for PG14 vs PG15."""

    conn = op.get_bind()
    dialect = conn.dialect.name

    op.execute(f"DROP INDEX IF EXISTS {index_name};")

    if dialect != "postgresql":
        op.create_index(index_name, table, [column], unique=True)
        return

    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_{table}_{column};")

    vnum = int(conn.execute(text("SHOW server_version_num")).scalar())
    if vnum >= 150000:
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table} ({column}) NULLS NOT DISTINCT;
            """
        )
    else:
        # PG14 lacks NULLS NOT DISTINCT, so emulate "unique when NOT NULL" with a
        # partial unique index instead.
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table} ({column})
            WHERE {column} IS NOT NULL;
            """
        )


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    bind.execute(
        sa.text(
            """
            DELETE FROM copyright_bindings
            WHERE phrase_hash IS NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            DELETE FROM copyright_bindings
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY phrase_hash ORDER BY id) AS rn
                    FROM copyright_bindings
                    WHERE phrase_hash IS NOT NULL
                ) AS ordered
                WHERE ordered.rn > 1
            )
            """
        )
    )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("copyright_bindings", recreate="always") as batch_op:
            batch_op.alter_column(
                "phrase_hash",
                existing_type=sa.String(),
                type_=sa.String(length=64),
                nullable=False,
                existing_nullable=True,
            )
    else:
        op.alter_column(
            "copyright_bindings",
            "phrase_hash",
            existing_type=sa.String(),
            type_=sa.String(length=64),
            nullable=False,
            existing_nullable=True,
        )

    create_version_aware_unique_index(
        "copyright_bindings",
        "phrase_hash",
        "ux_copyright_bindings_phrase_hash",
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    _ = inspector

    op.execute("DROP INDEX IF EXISTS ux_copyright_bindings_phrase_hash;")

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("copyright_bindings", recreate="always") as batch_op:
            batch_op.alter_column(
                "phrase_hash",
                existing_type=sa.String(length=64),
                type_=sa.String(),
                nullable=True,
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "copyright_bindings",
            "phrase_hash",
            existing_type=sa.String(length=64),
            type_=sa.String(),
            nullable=True,
            existing_nullable=False,
        )
