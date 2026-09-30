"""Update admin audit logs schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

# revision identifiers, used by Alembic.
revision = "20260315_admin_audit_log_restructure"
down_revision = "20260301_admin_token_bootstrap"
branch_labels = None
depends_on = None


AUDIT_TABLE = sa.Table(
    "admin_audit_logs",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("metadata", sa.JSON),
    sa.Column("target_user_id", sa.Integer),
)


def upgrade() -> None:
    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.alter_column(
            "operator_user_id",
            new_column_name="user_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        batch.alter_column(
            "created_at",
            new_column_name="timestamp",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            existing_server_default=sa.func.now(),
        )
        batch.alter_column(
            "details",
            new_column_name="metadata",
            existing_type=sa.JSON(),
            existing_nullable=True,
        )

    bind = op.get_bind()
    session = orm.Session(bind=bind)
    try:
        rows = session.execute(
            sa.select(
                AUDIT_TABLE.c.id, AUDIT_TABLE.c.metadata, AUDIT_TABLE.c.target_user_id
            )
        ).mappings()
        for row in rows:
            target_user_id = row.get("target_user_id")
            if target_user_id is None:
                continue
            metadata = row.get("metadata") or {}
            if isinstance(metadata, dict) and "target_user_id" in metadata:
                continue
            updated_metadata = dict(metadata)
            updated_metadata.setdefault("target_user_id", target_user_id)
            session.execute(
                AUDIT_TABLE.update()
                .where(AUDIT_TABLE.c.id == row["id"])
                .values(metadata=updated_metadata)
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.drop_column("target_user_id")
        batch.alter_column(
            "timestamp",
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=False,
            existing_server_default=sa.func.now(),
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.alter_column(
            "timestamp",
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            existing_server_default=sa.func.now(),
        )
        batch.add_column(
            sa.Column(
                "target_user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )

    bind = op.get_bind()
    session = orm.Session(bind=bind)
    try:
        rows = session.execute(
            sa.select(AUDIT_TABLE.c.id, AUDIT_TABLE.c.metadata)
        ).mappings()
        for row in rows:
            metadata = row.get("metadata") or {}
            target_user_id = None
            if isinstance(metadata, dict):
                target_user_id = metadata.get("target_user_id")
            session.execute(
                AUDIT_TABLE.update()
                .where(AUDIT_TABLE.c.id == row["id"])
                .values(target_user_id=target_user_id)
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.alter_column(
            "metadata",
            new_column_name="details",
            existing_type=sa.JSON(),
            existing_nullable=True,
        )
        batch.alter_column(
            "timestamp",
            new_column_name="created_at",
            existing_type=sa.DateTime(),
            existing_nullable=False,
            existing_server_default=sa.func.now(),
        )
        batch.alter_column(
            "user_id",
            new_column_name="operator_user_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
