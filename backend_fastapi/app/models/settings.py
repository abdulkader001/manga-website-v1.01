from sqlalchemy import (
    DDL,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    Index,
    event,
    func,
)
from sqlalchemy.orm import relationship, synonym

from .base import Base
from ..utils.email_crypto import (
    decrypt_email,
    encrypt_email,
    hash_email,
    normalize_email,
    render_email,
)


class FooterSettings(Base):
    __tablename__ = "footer_settings"
    id = Column(Integer, primary_key=True)
    contact = Column(Text, nullable=True)
    terms = Column(Text, nullable=True)
    privacy = Column(Text, nullable=True)
    socials = Column(JSON, nullable=True)  # list of { "label": "...", "url": "..." }


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)


class AdSlot(Base):
    __tablename__ = "ad_slots"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    slot_key = Column(String(100), unique=True, nullable=False)
    slot_group = Column(String(100), nullable=True)
    # Named region of the site this slot renders in (see services/ad_placements).
    # Nullable means "configured but not placed", so admins can stage a slot
    # without it going live.
    placement = Column(String(50), nullable=True, index=True)
    # Ordering within a placement when several slots share it.
    position = Column(Integer, nullable=False, default=0, server_default="0")
    # Admin-tunable sizing; NULL leaves it to the stylesheet.
    height_px = Column(Integer, nullable=True)
    max_width_px = Column(Integer, nullable=True)
    type = Column(String(20), nullable=False, default="image")
    image_url = Column(String(500), nullable=True)
    link_url = Column(String(500), nullable=True)
    alt_text = Column(String(255), nullable=True)
    html_code = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    provider_id = Column(Integer, ForeignKey("global_ad_providers.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    provider = relationship("GlobalAdProvider", lazy="selectin", back_populates="slots")
    clicks = relationship(
        "AdClick",
        lazy="selectin",
        back_populates="slot",
        cascade="all, delete-orphan",
    )

    # Compatibility aliases for older admin endpoints
    link = synonym("link_url")
    active = synonym("enabled")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slot_key": self.slot_key,
            "slot_group": self.slot_group,
            "placement": self.placement,
            "position": self.position or 0,
            "height_px": self.height_px,
            "max_width_px": self.max_width_px,
            "type": self.type,
            "image_url": self.image_url,
            "link_url": self.link_url,
            "link": self.link_url,
            "alt_text": self.alt_text,
            "enabled": bool(self.enabled),
            "active": bool(self.enabled),
            "metadata": self.metadata_json or {},
            "provider_id": self.provider_id,
            "provider_name": self.provider.name if self.provider else None,
            "html_code": self.html_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GlobalAdProvider(Base):
    __tablename__ = "global_ad_providers"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    config = Column(JSON, nullable=True)

    slots = relationship("AdSlot", lazy="selectin", back_populates="provider")


class AdClick(Base):
    __tablename__ = "ad_clicks"

    id = Column(Integer, primary_key=True)
    slot_id = Column(
        Integer, ForeignKey("ad_slots.id", ondelete="CASCADE"), nullable=False
    )
    user_email_encrypted = Column("user_email", String(512), nullable=True)
    user_email_hash = Column(String(128), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    slot = relationship("AdSlot", lazy="selectin", back_populates="clicks")

    @property
    def user_email(self) -> str | None:
        return render_email(self.user_email_encrypted)

    @user_email.setter
    def user_email(self, value: str | None) -> None:
        normalized = normalize_email(value)
        if normalized is None:
            self.user_email_encrypted = None
            self.user_email_hash = None
            return
        self.user_email_encrypted = encrypt_email(normalized) or normalized
        self.user_email_hash = hash_email(normalized)

    @property
    def user_email_plaintext(self) -> str | None:
        return decrypt_email(self.user_email_encrypted)


class AdminBootstrapState(Base):
    __tablename__ = "admin_bootstrap_state"

    id = Column(Integer, primary_key=True, default=1)
    admin_initialized = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    initialized_at = Column(DateTime, nullable=True)
    initialized_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_token_issued_at = Column(DateTime, nullable=True)
    last_token_redeemed_at = Column(DateTime, nullable=True)


class SystemState(Base):
    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, default=1)
    secret_phrase_used = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    main_admin_email_encrypted = Column("main_admin_email", String(512), nullable=True)
    main_admin_email_hash = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def main_admin_email(self) -> str | None:
        return render_email(self.main_admin_email_encrypted)

    @main_admin_email.setter
    def main_admin_email(self, value: str | None) -> None:
        normalized = normalize_email(value)
        if normalized is None:
            self.main_admin_email_encrypted = None
            self.main_admin_email_hash = None
            return
        self.main_admin_email_encrypted = encrypt_email(normalized) or normalized
        self.main_admin_email_hash = hash_email(normalized)

    @property
    def main_admin_email_plaintext(self) -> str | None:
        return decrypt_email(self.main_admin_email_encrypted)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, default=1)
    local_ocr_enabled = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    local_ocr_engine = Column(String(100), nullable=True)
    # Session lifetime in days, admin-configurable (SRS 1D.5.1). Range 1–30,
    # default 14 (within the 10–20 day band). Enforced in the service layer.
    session_expiry_days = Column(
        Integer, nullable=False, default=14, server_default="14"
    )
    # Magic-link token TTL in minutes (SRS 1D.1A.3): default 15, range 5–60.
    magic_link_ttl_minutes = Column(
        Integer, nullable=False, default=15, server_default="15"
    )
    # SRS 2C.4.3 Mechanism A: whether the shared cache is offered as the
    # platform-wide default/first-priority source. "on" | "reduced" | "off".
    # Never affects Mechanism B (2C.4.4) -- a user's own opt-in sharing.
    cache_priority = Column(
        String(16), nullable=False, default="on", server_default="on"
    )
    # SRS 2F.2A: admin-curated overlay font list. NULL/empty falls back to
    # the built-in curated set in services.overlay_fonts -- editing this is
    # how an administrator adds to or curates the list without a code
    # change.
    overlay_fonts = Column(JSON, nullable=True)
    # SRS 2E.3: global daily ceiling on platform-default provider usage
    # (pages/day, aggregate across every user who isn't using their own
    # key). NULL = unbounded, subject only to each account's own limit.
    platform_default_daily_ceiling = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ProviderCredentials(Base):
    __tablename__ = "provider_credentials"

    id = Column(Integer, primary_key=True)
    provider_name = Column(String(100), nullable=False)
    provider = Column(String(120), nullable=False)
    api_key = Column(String(255), nullable=False)
    config = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    is_system = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "uq_provider_credentials_name_provider",
            "provider_name",
            "provider",
            "is_system",
            unique=True,
        ),
    )


class AdminPromotionToken(Base):
    __tablename__ = "admin_promotion_tokens"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    issued_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    issued_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_to_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    redeemed_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_source_ip = Column(String(45), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(255), nullable=True)
    context = Column(JSON, nullable=True)

    issued_by_user = relationship(
        "User",
        lazy="selectin",
        foreign_keys=[issued_by_user_id],
        back_populates="issued_promotion_tokens",
    )
    issued_to_user = relationship(
        "User",
        lazy="selectin",
        foreign_keys=[issued_to_user_id],
        back_populates="assigned_promotion_tokens",
    )
    redeemed_by_user = relationship(
        "User",
        lazy="selectin",
        foreign_keys=[redeemed_by_user_id],
        back_populates="redeemed_promotion_tokens",
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    # High-volume, append-only table (SRS 1C.3.6): partition key is time. The
    # timestamp index keeps time-ordered pagination bounded as the log grows,
    # and the user_id index avoids an unindexed-FK scan when filtering by actor.
    __table_args__ = (
        Index("ix_admin_audit_logs_timestamp", "timestamp"),
        Index("ix_admin_audit_logs_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    operator = Column(String(255), nullable=True)
    action = Column(String(255), nullable=False)
    metadata_json = Column("metadata", JSON, nullable=True)
    source_ip = Column(String(45), nullable=True)
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship(
        "User", lazy="selectin", foreign_keys=[user_id], back_populates="audit_logs"
    )


# F-3: the "append-only" claim above was aspirational -- nothing enforced it.
# ORM-level guards (before_update/before_delete mapper events) only catch
# ORM-object writes; they are silently skipped by bulk
# ``Query.filter(...).update()``/``.delete()``, which is exactly how a
# runtime probe against a live row overwrote action/metadata/operator and
# deleted rows outright. Only a database-level trigger sees every statement
# regardless of how it was issued, so that's what's registered here.
#
# The only mutation that must still succeed is the users.id FK's
# ``ON DELETE SET NULL``, which performs a real UPDATE that only clears
# user_id -- allowed explicitly below so a deleted actor's audit trail
# survives with user_id NULL rather than the row itself disappearing.
#
# Fires on ``Base.metadata.create_all()`` (tests, via SQLAlchemy's
# ``after_create`` DDL event) covering the same two dialects as the
# equivalent Alembic migration
# (versions/20260827_admin_audit_logs_append_only.py), which is what actually
# installs this against a real deployment -- production schema is built by
# Alembic, never by ``create_all()``.
#
# Each DDL object below is a single statement: most DBAPI cursors (sqlite3
# included) reject a multi-statement string in one execute() call, so the
# function/trigger pair -- and the two SQLite triggers -- are registered as
# separate ``after_create`` listeners rather than one combined script.
_ADMIN_AUDIT_LOGS_POSTGRES_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION admin_audit_logs_append_only() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'admin_audit_logs is append-only: DELETE not permitted (id=%%)', OLD.id;
        ELSIF TG_OP = 'UPDATE' THEN
            -- metadata is `json`, not `jsonb` -- Postgres's json type has no
            -- equality operator at all (unlike jsonb), so compare the raw
            -- text representation instead.
            IF NEW.user_id IS NOT NULL
               OR NEW.operator IS DISTINCT FROM OLD.operator
               OR NEW.action IS DISTINCT FROM OLD.action
               OR NEW."metadata"::text IS DISTINCT FROM OLD."metadata"::text
               OR NEW.source_ip IS DISTINCT FROM OLD.source_ip
               OR NEW."timestamp" IS DISTINCT FROM OLD."timestamp" THEN
                RAISE EXCEPTION 'admin_audit_logs is append-only: only user_id may be cleared to NULL (id=%%)', OLD.id;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_ADMIN_AUDIT_LOGS_POSTGRES_TRIGGER = DDL(
    """
    DROP TRIGGER IF EXISTS admin_audit_logs_append_only ON admin_audit_logs;
    """
)

_ADMIN_AUDIT_LOGS_POSTGRES_TRIGGER_CREATE = DDL(
    """
    CREATE TRIGGER admin_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON admin_audit_logs
    FOR EACH ROW EXECUTE FUNCTION admin_audit_logs_append_only();
    """
)

_ADMIN_AUDIT_LOGS_SQLITE_NO_DELETE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS admin_audit_logs_no_delete
    BEFORE DELETE ON admin_audit_logs
    BEGIN
        SELECT RAISE(ABORT, 'admin_audit_logs is append-only: DELETE not permitted');
    END;
    """
)

_ADMIN_AUDIT_LOGS_SQLITE_NO_MUTATE = DDL(
    """
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
)

for _ddl in (
    _ADMIN_AUDIT_LOGS_POSTGRES_FUNCTION,
    _ADMIN_AUDIT_LOGS_POSTGRES_TRIGGER,
    _ADMIN_AUDIT_LOGS_POSTGRES_TRIGGER_CREATE,
):
    event.listen(AdminAuditLog.__table__, "after_create", _ddl.execute_if(dialect="postgresql"))

for _ddl in (_ADMIN_AUDIT_LOGS_SQLITE_NO_DELETE, _ADMIN_AUDIT_LOGS_SQLITE_NO_MUTATE):
    event.listen(AdminAuditLog.__table__, "after_create", _ddl.execute_if(dialect="sqlite"))


class VaultSecret(Base):
    """Admin-managed override for an allow-listed environment variable.

    ``value_encrypted`` is a Fernet token under ``INTEGRATIONS_SECRET`` (see
    ``services/secret_vault.py``); the plaintext never touches the database.
    A row here wins over the same key in ``.env``; deleting it falls back to
    ``.env`` again.
    """

    __tablename__ = "vault_secrets"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value_encrypted = Column(Text, nullable=False)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
