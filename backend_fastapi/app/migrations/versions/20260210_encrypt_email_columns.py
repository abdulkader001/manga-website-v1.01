"""Encrypt email columns and add hashed indexes"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

from backend_fastapi.app.utils.email_crypto import (
    decrypt_email,
    encrypt_email,
    hash_email,
    normalize_email,
)

# revision identifiers, used by Alembic.
revision = "20260210_encrypt_email_columns"
down_revision = "20260115_add_is_active_to_users"
branch_labels = None
depends_on = None


def _update_emails(
    session: orm.Session,
    table: sa.Table,
    id_column: sa.Column,
    email_column: sa.Column,
    hash_column: sa.Column,
    *,
    allow_null: bool,
) -> None:
    rows = session.execute(sa.select(id_column, email_column)).mappings()
    for row in rows:
        record_id = row[id_column.name]
        raw_email = row[email_column.name]
        if raw_email is None:
            if allow_null:
                session.execute(
                    table.update()
                    .where(id_column == record_id)
                    .values({hash_column.name: None})
                )
            continue

        decrypted = decrypt_email(raw_email)
        normalized = normalize_email(decrypted or raw_email)
        if not normalized:
            if allow_null:
                session.execute(
                    table.update()
                    .where(id_column == record_id)
                    .values({email_column.name: None, hash_column.name: None})
                )
            continue

        ciphertext = encrypt_email(normalized)
        hashed = hash_email(normalized)

        session.execute(
            table.update()
            .where(id_column == record_id)
            .values(
                {
                    email_column.name: ciphertext or normalized,
                    hash_column.name: hashed,
                }
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            type_=sa.String(length=512),
        )
        batch_op.add_column(
            sa.Column("email_hash", sa.String(length=128), nullable=True)
        )

    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("users")
    }
    constraint_name = None
    if "uq_users_email" in unique_constraints:
        constraint_name = "uq_users_email"
    else:
        for candidate in unique_constraints:
            if candidate and "email" in candidate:
                constraint_name = candidate
                break
    with op.batch_alter_table("users") as batch_op:
        if constraint_name:
            batch_op.drop_constraint(constraint_name, type_="unique")
        batch_op.create_unique_constraint("uq_users_email_hash", ["email_hash"])

    if "login_tokens" in inspector.get_table_names():
        with op.batch_alter_table("login_tokens") as batch_op:
            batch_op.alter_column(
                "email",
                existing_type=sa.String(length=255),
                type_=sa.String(length=512),
            )
            batch_op.add_column(
                sa.Column("email_hash", sa.String(length=128), nullable=True)
            )
            batch_op.create_index(
                "ix_login_tokens_email_hash", ["email_hash"], unique=False
            )

    with op.batch_alter_table("ad_clicks") as batch_op:
        batch_op.alter_column(
            "user_email",
            existing_type=sa.String(length=255),
            type_=sa.String(length=512),
        )
        batch_op.add_column(
            sa.Column("user_email_hash", sa.String(length=128), nullable=True)
        )
        batch_op.create_index(
            "ix_ad_clicks_user_email_hash", ["user_email_hash"], unique=False
        )

    with op.batch_alter_table("system_state") as batch_op:
        batch_op.alter_column(
            "main_admin_email",
            existing_type=sa.String(length=255),
            type_=sa.String(length=512),
        )
        batch_op.add_column(
            sa.Column("main_admin_email_hash", sa.String(length=128), nullable=True),
        )
        batch_op.create_index(
            "ix_system_state_main_admin_email_hash",
            ["main_admin_email_hash"],
            unique=False,
        )

    session = orm.Session(bind=bind)

    users_table = sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("email", sa.String),
        sa.Column("email_hash", sa.String),
    )
    if "login_tokens" in inspector.get_table_names():
        login_tokens_table = sa.Table(
            "login_tokens",
            sa.MetaData(),
            sa.Column("id", sa.Integer),
            sa.Column("email", sa.String),
            sa.Column("email_hash", sa.String),
        )
    else:
        login_tokens_table = None

    ad_clicks_table = sa.Table(
        "ad_clicks",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("user_email", sa.String),
        sa.Column("user_email_hash", sa.String),
    )
    system_state_table = sa.Table(
        "system_state",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("main_admin_email", sa.String),
        sa.Column("main_admin_email_hash", sa.String),
    )

    try:
        _update_emails(
            session,
            users_table,
            users_table.c.id,
            users_table.c.email,
            users_table.c.email_hash,
            allow_null=False,
        )
        if login_tokens_table is not None:
            _update_emails(
                session,
                login_tokens_table,
                login_tokens_table.c.id,
                login_tokens_table.c.email,
                login_tokens_table.c.email_hash,
                allow_null=False,
            )
        _update_emails(
            session,
            ad_clicks_table,
            ad_clicks_table.c.id,
            ad_clicks_table.c.user_email,
            ad_clicks_table.c.user_email_hash,
            allow_null=True,
        )
        _update_emails(
            session,
            system_state_table,
            system_state_table.c.id,
            system_state_table.c.main_admin_email,
            system_state_table.c.main_admin_email_hash,
            allow_null=True,
        )
        session.commit()
    finally:
        session.close()

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email_hash", existing_type=sa.String(length=128), nullable=False
        )
    if "login_tokens" in inspector.get_table_names():
        with op.batch_alter_table("login_tokens") as batch_op:
            batch_op.alter_column(
                "email_hash",
                existing_type=sa.String(length=128),
                nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "login_tokens" in inspector.get_table_names():
        with op.batch_alter_table("login_tokens") as batch_op:
            batch_op.alter_column(
                "email_hash", existing_type=sa.String(length=128), nullable=True
            )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email_hash", existing_type=sa.String(length=128), nullable=True
        )

    with op.batch_alter_table("system_state") as batch_op:
        batch_op.drop_index("ix_system_state_main_admin_email_hash")
        batch_op.drop_column("main_admin_email_hash")
        batch_op.alter_column(
            "main_admin_email",
            existing_type=sa.String(length=512),
            type_=sa.String(length=255),
        )

    with op.batch_alter_table("ad_clicks") as batch_op:
        batch_op.drop_index("ix_ad_clicks_user_email_hash")
        batch_op.drop_column("user_email_hash")
        batch_op.alter_column(
            "user_email",
            existing_type=sa.String(length=512),
            type_=sa.String(length=255),
        )

    if "login_tokens" in inspector.get_table_names():
        with op.batch_alter_table("login_tokens") as batch_op:
            batch_op.drop_index("ix_login_tokens_email_hash")
            batch_op.drop_column("email_hash")
            batch_op.alter_column(
                "email",
                existing_type=sa.String(length=512),
                type_=sa.String(length=255),
            )

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_email_hash", type_="unique")
        batch_op.drop_column("email_hash")
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=512),
            type_=sa.String(length=255),
        )
        batch_op.create_unique_constraint("uq_users_email", ["email"])
