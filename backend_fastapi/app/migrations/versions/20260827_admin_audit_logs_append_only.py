"""Enforce admin_audit_logs is genuinely append-only (F-3)

The table and ``utils/audit_logger.py`` docstrings both asserted "append-only"
with nothing enforcing it: an ORM attribute update + commit, a bulk
``Query.filter(...).update(...)``, an ORM ``session.delete()``, and a bulk
``Query.filter(...).delete()`` all succeeded against a live row in testing.
ORM-level ``before_update``/``before_delete`` mapper events would only catch
the first and third of those -- bulk ``Query.update()``/``.delete()`` bypass
the unit-of-work entirely, which is exactly how the runtime probe overwrote
action/metadata/operator and deleted rows outright. Only a database-level
trigger sees every statement regardless of how it was issued.

The trigger allows exactly one mutation: the ``users.id`` foreign key's
``ON DELETE SET NULL``, which performs a real UPDATE that only clears
``user_id`` -- needed so a deleted actor's audit trail survives with
``user_id`` NULL rather than the row disappearing. Any other UPDATE, or any
DELETE, is rejected.

This mirrors the ``after_create`` event listeners registered on
``AdminAuditLog.__table__`` in ``app/models/settings.py`` (which cover the
same two dialects for ``Base.metadata.create_all()`` -- the path the test
suite uses to build its schema). Keep both in sync if this trigger's logic
ever changes.
"""

from alembic import op

revision = "20260827_admin_audit_logs_append_only"
down_revision = "20260817_create_system_settings_table"
branch_labels = None
depends_on = None

_POSTGRES_FUNCTION = """
CREATE OR REPLACE FUNCTION admin_audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admin_audit_logs is append-only: DELETE not permitted (id=%)', OLD.id;
    ELSIF TG_OP = 'UPDATE' THEN
        -- metadata is `json`, not `jsonb` -- Postgres's json type has no
        -- equality operator at all (unlike jsonb), so compare the raw text
        -- representation instead.
        IF NEW.user_id IS NOT NULL
           OR NEW.operator IS DISTINCT FROM OLD.operator
           OR NEW.action IS DISTINCT FROM OLD.action
           OR NEW."metadata"::text IS DISTINCT FROM OLD."metadata"::text
           OR NEW.source_ip IS DISTINCT FROM OLD.source_ip
           OR NEW."timestamp" IS DISTINCT FROM OLD."timestamp" THEN
            RAISE EXCEPTION 'admin_audit_logs is append-only: only user_id may be cleared to NULL (id=%)', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_POSTGRES_DROP_TRIGGER = "DROP TRIGGER IF EXISTS admin_audit_logs_append_only ON admin_audit_logs;"

_POSTGRES_CREATE_TRIGGER = """
CREATE TRIGGER admin_audit_logs_append_only
BEFORE UPDATE OR DELETE ON admin_audit_logs
FOR EACH ROW EXECUTE FUNCTION admin_audit_logs_append_only();
"""

_POSTGRES_DROP_FUNCTION = "DROP FUNCTION IF EXISTS admin_audit_logs_append_only();"

_SQLITE_NO_DELETE = """
CREATE TRIGGER IF NOT EXISTS admin_audit_logs_no_delete
BEFORE DELETE ON admin_audit_logs
BEGIN
    SELECT RAISE(ABORT, 'admin_audit_logs is append-only: DELETE not permitted');
END;
"""

_SQLITE_NO_MUTATE = """
CREATE TRIGGER IF NOT EXISTS admin_audit_logs_no_mutate
BEFORE UPDATE ON admin_audit_logs
WHEN NEW.user_id IS NOT NULL
  OR NEW.operator IS NOT OLD.operator
  OR NEW.action IS NOT OLD.action
  OR NEW."metadata" IS NOT OLD."metadata"
  OR NEW.source_ip IS NOT OLD.source_ip
  OR NEW."timestamp" IS NOT OLD."timestamp"
BEGIN
    SELECT RAISE(ABORT, 'admin_audit_logs is append-only: only user_id may be cleared to NULL');
END;
"""

_SQLITE_DROP_NO_DELETE = "DROP TRIGGER IF EXISTS admin_audit_logs_no_delete;"
_SQLITE_DROP_NO_MUTATE = "DROP TRIGGER IF EXISTS admin_audit_logs_no_mutate;"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(_POSTGRES_FUNCTION)
        op.execute(_POSTGRES_DROP_TRIGGER)
        op.execute(_POSTGRES_CREATE_TRIGGER)
    elif dialect == "sqlite":
        op.execute(_SQLITE_NO_DELETE)
        op.execute(_SQLITE_NO_MUTATE)
    # Other dialects: no-op. This app only ships Postgres (production) and
    # SQLite (dev/test) configurations.


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(_POSTGRES_DROP_TRIGGER)
        op.execute(_POSTGRES_DROP_FUNCTION)
    elif dialect == "sqlite":
        op.execute(_SQLITE_DROP_NO_DELETE)
        op.execute(_SQLITE_DROP_NO_MUTATE)
