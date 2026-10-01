"""One inbox, one account: unique canonical-email identity per user.

Revision ID: 20261010_email_identity
Revises: 20261009_login_required

Adds ``users.email_identity_hash`` (unique) and fills it for existing
accounts, oldest first. If two old accounts turn out to share one inbox
(``john.doe@gmail.com`` and ``johndoe@gmail.com``), the oldest keeps it and the
later one is left empty and logged for the admin to review; no new duplicate
can be created after this. Rows whose address can't be decrypted here are
filled in on their next sign-in.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "20261010_email_identity"
down_revision = "20261009_login_required"
branch_labels = None
depends_on = None

TABLE = "users"
COLUMN = "email_identity_hash"
INDEX = "ix_users_email_identity_hash"

log = logging.getLogger("alembic.email_identity")


def _backfill(bind) -> None:
    from backend_fastapi.app.utils.email_crypto import decrypt_email, email_identity

    users = sa.table(
        TABLE, sa.column("id"), sa.column("email"), sa.column(COLUMN)
    )
    rows = bind.execute(
        sa.select(users.c.id, users.c.email).where(users.c[COLUMN].is_(None)).order_by(users.c.id)
    ).all()
    taken = {
        value
        for (value,) in bind.execute(sa.select(users.c[COLUMN]).where(users.c[COLUMN].isnot(None)))
    }
    for user_id, stored in rows:
        try:
            plain = decrypt_email(stored)
        except Exception:
            plain = None
        identity = email_identity(plain) if plain and "@" in plain else None
        if not identity:
            continue
        if identity in taken:
            log.warning("email_identity_duplicate user_id=%s (an older account owns this inbox)", user_id)
            continue
        bind.execute(users.update().where(users.c.id == user_id).values({COLUMN: identity}))
        taken.add(identity)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    if COLUMN not in {c["name"] for c in inspector.get_columns(TABLE)}:
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=64), nullable=True))
    try:
        _backfill(bind)
    except Exception:  # never block the upgrade; sign-in heals the rest
        log.exception("email_identity_backfill_failed")
    if INDEX not in {i["name"] for i in inspector.get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, [COLUMN], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    if INDEX in {i["name"] for i in inspector.get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    if COLUMN in {c["name"] for c in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, COLUMN)
