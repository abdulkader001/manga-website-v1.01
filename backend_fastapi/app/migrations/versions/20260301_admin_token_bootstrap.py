"""Replace secret phrase workflow with admin promotion tokens"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

# revision identifiers, used by Alembic.
revision = "20260301_admin_token_bootstrap"
down_revision = "20260210_encrypt_email_columns"
branch_labels = None
depends_on = None


ADMIN_AUDIT_OLD = sa.Table(
    "admin_audit",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("actor_user_id", sa.Integer),
    sa.Column("action", sa.String(length=255)),
    sa.Column("details", sa.JSON),
    sa.Column("created_at", sa.DateTime),
)


def upgrade() -> None:
    conn = op.get_bind()
    session = orm.Session(bind=conn)

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("operator", sa.String(length=255), nullable=True),
        sa.Column(
            "operator_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column(
            "target_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )

    try:
        rows = session.execute(sa.select(ADMIN_AUDIT_OLD)).mappings()
        for row in rows:
            session.execute(
                sa.text(
                    "INSERT INTO admin_audit_logs (id, operator_user_id, action, details, created_at) "
                    "VALUES (:id, :operator_user_id, :action, :details, :created_at)"
                ),
                {
                    "id": row["id"],
                    "operator_user_id": row.get("actor_user_id"),
                    "action": row.get("action"),
                    "details": row.get("details"),
                    "created_at": row.get("created_at"),
                },
            )
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()

    op.drop_table("admin_audit")

    op.create_table(
        "admin_promotion_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "issued_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "issued_to_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "redeemed_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("redeemed_source_ip", sa.String(length=45), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=255), nullable=True),
        sa.Column("context", sa.JSON, nullable=True),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_admin_promotion_tokens_token_hash",
        "admin_promotion_tokens",
        ["token_hash"],
        unique=True,
    )

    with op.batch_alter_table("admin_bootstrap_state") as batch:
        batch.drop_column("secret_phrase_hash")
        batch.drop_column("secret_phrase_used_at")
        batch.add_column(
            sa.Column("last_token_issued_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(
            sa.Column("last_token_redeemed_at", sa.DateTime(), nullable=True)
        )

    op.drop_table("secret_phrase_attempts")


def downgrade() -> None:
    op.create_table(
        "secret_phrase_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "success", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )

    with op.batch_alter_table("admin_bootstrap_state") as batch:
        batch.drop_column("last_token_issued_at")
        batch.drop_column("last_token_redeemed_at")
        batch.add_column(
            sa.Column("secret_phrase_hash", sa.String(length=128), nullable=True)
        )
        batch.add_column(
            sa.Column("secret_phrase_used_at", sa.DateTime(), nullable=True)
        )

    op.drop_index(
        "ix_admin_promotion_tokens_token_hash", table_name="admin_promotion_tokens"
    )
    op.drop_table("admin_promotion_tokens")

    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )

    conn = op.get_bind()
    session = orm.Session(bind=conn)
    try:
        rows = session.execute(sa.text("SELECT * FROM admin_audit_logs")).mappings()
        for row in rows:
            session.execute(
                sa.text(
                    "INSERT INTO admin_audit (id, actor_user_id, action, details, created_at) "
                    "VALUES (:id, :actor_user_id, :action, :details, :created_at)"
                ),
                {
                    "id": row["id"],
                    "actor_user_id": row.get("operator_user_id"),
                    "action": row.get("action"),
                    "details": row.get("details"),
                    "created_at": row.get("created_at"),
                },
            )
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()

    op.drop_table("admin_audit_logs")
