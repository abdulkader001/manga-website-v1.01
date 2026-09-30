"""Add comments.parent_id FK with ON DELETE SET NULL, not CASCADE (F-34)

``comments.parent_id`` was added as a bare nullable column by
20260722_native_comments_core (no FK constraint ever created), while the ORM
model has always declared it as a self-referential FK. That's schema drift
independent of F-34: a real Postgres deployment built via this migration
chain has no referential integrity on parent_id at all today. This migration
both closes that gap and picks the safe action while doing so.

The unsafe action would have been ON DELETE CASCADE, matching what
``Base.metadata.create_all()`` (the test suite's schema path) produced before
this fix: combined with ``User.comments``'s own
``cascade="all, delete-orphan"``, a hard user-delete would transitively
delete every reply beneath every comment that user posted, however deep,
regardless of who wrote those replies -- undercutting the non-destructive
moderator-removal design (a ``removed_at`` flag, row kept) the moment any
account-deletion feature is built. ON DELETE SET NULL instead turns a
deleted parent's replies into top-level comments rather than deleting them.
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260828_comments_parent_fk_set_null"
down_revision = "20260827_admin_audit_logs_append_only"
branch_labels = None
depends_on = None

TABLE = "comments"
FK_NAME = "fk_comments_parent_id_comments"


def _existing_parent_fk(inspector):
    for fk in inspector.get_foreign_keys(TABLE):
        if fk.get("constrained_columns") == ["parent_id"]:
            return fk
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return

    existing = _existing_parent_fk(inspector)
    if existing and existing.get("options", {}).get("ondelete", "").upper() == "SET NULL":
        return  # already correct (e.g. schema built by create_all())

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch_op:
            if existing and existing.get("name"):
                batch_op.drop_constraint(existing["name"], type_="foreignkey")
            batch_op.create_foreign_key(
                FK_NAME, TABLE, ["parent_id"], ["id"], ondelete="SET NULL"
            )
    else:
        if existing and existing.get("name"):
            op.drop_constraint(existing["name"], TABLE, type_="foreignkey")
        op.create_foreign_key(
            FK_NAME, TABLE, TABLE, ["parent_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(TABLE):
        return

    existing = _existing_parent_fk(inspector)
    if not existing or not existing.get("name"):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch_op:
            batch_op.drop_constraint(existing["name"], type_="foreignkey")
    else:
        op.drop_constraint(existing["name"], TABLE, type_="foreignkey")
