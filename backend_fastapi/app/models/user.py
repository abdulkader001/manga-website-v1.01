import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Enum,
    Index,
    Text,
    JSON,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import expression

from .base import Base
from ..utils.email_crypto import (
    allow_email_decryption,
    can_decrypt_emails,
    decrypt_email,
    decrypt_secret,
    email_identity,
    email_lookup,
    encrypt_email,
    encrypt_secret,
    hash_email,
    mask_email,
    normalize_email,
    render_email,
)


# ----------------
# Enum for user roles
# ----------------
class UserRole(enum.Enum):
    """Three roles: main admin (ADMIN / PERMANENT, one merged owner tier),
    sub-admin (SECONDARY) and user (USER)."""

    USER = "user"
    # Retired: kept only because the Postgres enum type still has the value.
    # Nothing assigns it, migration 20261007 converted existing rows to USER,
    # and effective_role() resolves any leftover row to USER.
    MODERATOR = "moderator"
    SECONDARY = "secondary_admin"
    ADMIN = "admin"
    PERMANENT = "permanent_admin"


# ----------------
# User model
# ----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email_encrypted = Column("email", String(512), nullable=False, unique=True)
    email_hash = Column(String(128), unique=True, nullable=False, index=True)
    # C2: fast, deterministic HMAC lookup value for indexed login-by-email.
    email_lookup_hash = Column(String(64), unique=True, nullable=True, index=True)
    # One inbox, one account, for life: HMAC of the canonical mailbox
    # (gmail dots, googlemail.com and +tags folded). The unique constraint is
    # the hard guardrail; the address itself can never be changed.
    email_identity_hash = Column(String(64), unique=True, nullable=True, index=True)
    role = Column(
        Enum(UserRole, name="user_roles"), default=UserRole.USER, nullable=False
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=expression.true(),
    )
    is_main_admin = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_secondary_admin = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    provider = Column(String(50), nullable=True)
    # Verified-email state (SRS 1D.2.4). The sole purpose of verification on this
    # platform is to confirm a genuine, reachable email — set True once the user
    # proves control (clicks a magic link) or the OAuth provider asserts
    # email_verified. Used for promotions/announcements to real inboxes.
    #
    # F-57: this is NOT currently enforced as a gate anywhere. Every login path
    # (magic-link redemption, OAuth) already implies the user controls/verified
    # the email at login time, so nothing conditions behavior on this flag
    # today -- the only read site is user_settings.py's display-only account
    # summary. If you're adding a feature that should require a verified email
    # (e.g. "verified-only commenting"), this flag does not already do that;
    # you must add the check yourself.
    email_verified = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    email_verified_at = Column(DateTime, nullable=True)
    # Disposable-email post-creation detection (SRS 1H.7.1 / D5). Never an
    # auto-ban — D5's resolved safe default is flag-for-review, so a shared
    # dormitory/office network catching a false positive doesn't lock anyone
    # out; an administrator confirms before any account action.
    flagged_for_review = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    flag_reason = Column(String(64), nullable=True)
    flagged_at = Column(DateTime, nullable=True)
    # Community reputation (3C). Never directly settable -- it is the sum of
    # non-revoked ReputationEvent deltas (1E.5.3 / NEVER_GRANTABLE alter_rank).
    reputation = Column(Integer, nullable=False, default=0, server_default="0")
    # Moderator "block a user" from the community (1F.4.1) -- distinct from
    # account suspension/ban (is_active), which is a User Administration
    # power. A blocked user keeps their account but cannot post comments.
    community_blocked_at = Column(DateTime, nullable=True)
    community_blocked_reason = Column(String(255), nullable=True)
    community_blocked_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Moderator "time out a user for hours" (1F.4.1) -- expires on its own.
    community_timeout_until = Column(DateTime, nullable=True)
    community_timeout_reason = Column(String(255), nullable=True)
    # F-65: a bare server_default is not enough. The migration chain never
    # created that default on the real column, so every user inserted without
    # an explicit value got created_at=NULL, and GET /auth/me (whose UserRead
    # requires a datetime) then returned 500 for that user forever. The
    # Python-side default makes the application independent of database DDL;
    # the accompanying migration repairs the column itself.
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # "Sign out everywhere": every token issued at or before this instant is
    # refused, without writing a denylist row per outstanding token. Set by
    # the user's own logout-everywhere action and by an administrator
    # exercising the revoke_user_sessions permission. NULL means never revoked.
    sessions_revoked_before = Column(DateTime, nullable=True)

    # Admin second factor (roadmap item 15): a TOTP secret, encrypted at rest
    # like OAuth tokens. ``totp_enabled`` only turns true after the user proved
    # they can produce a code. ``totp_last_step`` is the last accepted 30 s
    # step, so one code cannot be used twice.
    totp_secret_encrypted = Column("totp_secret", Text, nullable=True)
    totp_enabled = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    totp_last_step = Column(BigInteger, nullable=True)

    username = Column(String(150), nullable=True)
    name = Column(String(150), nullable=True)
    google_sub = Column(String(255), unique=True, nullable=True)
    permanent = Column(Boolean, default=False, server_default="false")
    language = Column(String(10), nullable=False, default="en", server_default="en")

    # OAuth profile fields
    profile_image = Column(String(500), nullable=True)

    # Reader profile (completed once after first sign-in). ``birth_date`` drives
    # the under-18 content gate; ``password_hash`` is optional -- magic link
    # and OAuth accounts never need one.
    microsoft_sub = Column(String(255), unique=True, nullable=True)
    birth_date = Column(Date, nullable=True)
    gender = Column(String(32), nullable=True)
    profile_completed = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    password_hash = Column(String(255), nullable=True)
    failed_login_count = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    login_locked_until = Column(DateTime, nullable=True)

    # OAuth tokens are encrypted at rest (Blind Spot #16). The DB columns keep
    # their original names; access is via the access_token/refresh_token
    # properties below, which transparently encrypt/decrypt. Widened to Text
    # because ciphertext is longer than the plaintext token.
    refresh_token_encrypted = Column("refresh_token", Text, nullable=True)
    access_token_encrypted = Column("access_token", Text, nullable=True)

    # Relationships
    read_history = relationship(
        "ReadHistory",
        lazy="select",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    bookmarks = relationship(
        "Bookmark", lazy="select", back_populates="user", cascade="all, delete-orphan"
    )
    complaints = relationship(
        "Complaint",
        lazy="select",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # F-3: deliberately no cascade. AdminAuditLog.user_id is
    # ON DELETE SET NULL at the DB level, and the append-only trigger on
    # admin_audit_logs (models/settings.py) only permits that one column to
    # be nulled -- a "consistency cleanup" adding
    # cascade="all, delete-orphan" here would turn user deletion into
    # audit-trail deletion, which the trigger would then reject outright.
    audit_logs = relationship(
        "AdminAuditLog",
        lazy="select",
        foreign_keys="[AdminAuditLog.user_id]",
        back_populates="user",
    )
    api_keys = relationship(
        "UserAPIKey",
        lazy="select",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    processing_settings = relationship(
        "UserProcessingSettings",
        lazy="select",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # F-34: this cascade hard-deletes every comment the user authored, at
    # any depth, the moment a User row is deleted. Combined with
    # Comment.parent_id's independently-configured ondelete="SET NULL"
    # (below, near the Comment class), a hard user-delete does NOT delete
    # replies to those comments written by OTHER users -- they survive,
    # reparented to top-level -- but the deleted user's own comments are
    # gone for good rather than soft-removed (contrast the removed_at
    # flag-and-keep design used for moderator takedowns). No account-
    # deletion feature exists today, so this is latent, not exploited; see
    # test_orm_relationships.py::test_user_delete_hard_deletes_own_comments_but_orphans_other_users_replies
    # for the behavior this locks in. Do not change this cascade without a
    # deliberate product decision on what account deletion should do to a
    # user's comment history and to threads they participated in.
    comments = relationship(
        "Comment",
        lazy="select",
        foreign_keys="[Comment.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    issued_promotion_tokens = relationship(
        "AdminPromotionToken",
        lazy="select",
        foreign_keys="[AdminPromotionToken.issued_by_user_id]",
        back_populates="issued_by_user",
    )
    assigned_promotion_tokens = relationship(
        "AdminPromotionToken",
        lazy="select",
        foreign_keys="[AdminPromotionToken.issued_to_user_id]",
        back_populates="issued_to_user",
    )
    redeemed_promotion_tokens = relationship(
        "AdminPromotionToken",
        lazy="select",
        foreign_keys="[AdminPromotionToken.redeemed_by_user_id]",
        back_populates="redeemed_by_user",
    )

    @property
    def email(self) -> str | None:
        return render_email(self.email_encrypted)

    @email.setter
    def email(self, value: str | None) -> None:
        normalized = normalize_email(value)
        if normalized is None:
            raise ValueError("email is required")
        identity = email_identity(normalized)
        # Saved for life: an account's inbox can never be swapped for another.
        if self.email_identity_hash and self.email_identity_hash != identity:
            raise ValueError("an account's email address cannot be changed")
        self.email_encrypted = encrypt_email(normalized) or normalized
        hashed = hash_email(normalized)
        if hashed is None:
            raise ValueError("email hashing failed")
        self.email_hash = hashed
        self.email_lookup_hash = email_lookup(normalized)
        self.email_identity_hash = identity

    @property
    def email_plaintext(self) -> str | None:
        return decrypt_email(self.email_encrypted)

    @property
    def access_token(self) -> str | None:
        return decrypt_secret(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str | None) -> None:
        self.access_token_encrypted = encrypt_secret(value) if value else None

    @property
    def refresh_token(self) -> str | None:
        return decrypt_secret(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value: str | None) -> None:
        self.refresh_token_encrypted = encrypt_secret(value) if value else None

    def promote_to_permanent_admin(self):
        """Promote user to permanent admin (irreversible)."""
        if not self.permanent:
            self.role = UserRole.PERMANENT
            self.permanent = True

    def to_dict(self):
        masked_email = None
        if can_decrypt_emails():
            masked_email = mask_email(self.email_plaintext)
        return {
            "id": self.id,
            "email": self.email,
            # F-78: email_hash is an argon2id digest of the user's address.
            # It is a lookup key, not client-facing data -- shipping it in
            # admin user listings and /auth/me handed out an offline-crackable
            # hash of PII for every account. Nothing in the frontend reads it.
            "email_masked": masked_email,
            "role": self.role.value if self.role else None,
            "is_active": bool(getattr(self, "is_active", True)),
            "is_main_admin": bool(getattr(self, "is_main_admin", False)),
            "is_secondary_admin": bool(getattr(self, "is_secondary_admin", False)),
            "provider": self.provider,
            "email_verified": bool(getattr(self, "email_verified", False)),
            "username": self.username,
            "name": getattr(self, "name", None),
            "google_sub": self.google_sub,
            "permanent": self.permanent,
            "profile_image": self.profile_image,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "age": self.age,
            "is_under_18": self.is_under_18,
            "gender": self.gender,
            "profile_completed": bool(self.profile_completed),
            "has_password": bool(self.password_hash),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def age(self) -> int | None:
        if not self.birth_date:
            return None
        today = datetime.utcnow().date()
        born = self.birth_date
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    @property
    def is_under_18(self) -> bool:
        age = self.age
        return age is not None and age < 18

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)


class LoginToken(Base):
    __tablename__ = "login_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_encrypted = Column("email", String(512), nullable=False)
    email_hash = Column(String(128), nullable=False, index=True)
    # SRS 1D.1A.3: only a HASH of the token is stored. The plaintext exists only
    # in the emailed link, so a database breach yields no usable links. The DB
    # column is still named "token" (no migration); the attribute is token_hash.
    token_hash = Column("token", String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)

    user = relationship("User", lazy="selectin", backref="login_tokens")

    @property
    def email(self) -> str | None:
        return render_email(self.email_encrypted)

    @email.setter
    def email(self, value: str | None) -> None:
        normalized = normalize_email(value)
        if normalized is None:
            raise ValueError("email is required")
        self.email_encrypted = encrypt_email(normalized) or normalized
        hashed = hash_email(normalized)
        if hashed is None:
            raise ValueError("email hashing failed")
        self.email_hash = hashed

    @property
    def email_plaintext(self) -> str | None:
        return decrypt_email(self.email_encrypted)

    def mark_used(self) -> None:
        self.used_at = datetime.utcnow()

    def mark_expired(self) -> None:
        self.expires_at = datetime.utcnow()

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at


# ----------------
# UserAPIKey model
# ----------------
class UserAPIKey(Base):
    __tablename__ = "user_api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String(100), nullable=False)  # e.g. "ocr", "translation", "ai"
    api_key = Column(String(255), nullable=True)
    config = Column(
        JSON, nullable=True
    )  # provider metadata (api_url, model, headers, etc.)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", lazy="selectin", back_populates="api_keys")


class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    user = relationship("User", lazy="selectin", back_populates="complaints")


# SRS 3A.3/D14: reply nesting is capped so rendering stays manageable. A
# reply beyond this depth still threads correctly (parent_id is exact) but
# its stored `depth` clamps here, so the frontend collapses it into the last
# indentable level instead of drifting off-screen.
MAX_COMMENT_REPLY_DEPTH = 5

# SRS 3A.3: maximum comment length, enforced server-side (character counter
# is the frontend's job).
MAX_COMMENT_LENGTH = 2000


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        # Every thread listing filters by (target_type, target_id, parent_id
        # is NULL) (SRS 4A.3 -- indexes driven by real query patterns, see
        # comment_service.list_thread).
        Index("ix_comments_target_parent", "target_type", "target_id", "parent_id"),
        Index("ix_comments_parent_id", "parent_id"),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_type = Column(String(50), nullable=False)  # "manga" or "chapter"
    target_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Threading (3A.3)
    # F-34: SET NULL, not CASCADE. A self-referential ON DELETE CASCADE here
    # combined with User.comments' own cascade="all, delete-orphan" (see the
    # F-34 comment on that relationship, above the User class) meant a
    # hard user-delete would transitively delete every reply beneath every
    # comment that user posted, however deep, regardless of who wrote those
    # replies -- undercutting the non-destructive moderator-removal design
    # (removed_at flag, row kept) with a much larger blast radius the moment
    # any account-deletion feature is built. A deleted parent's replies now
    # become top-level (parent_id NULL) instead of disappearing. This does
    # NOT make User.comments' own cascade safe by itself -- the deleted
    # user's own comments are still hard-deleted, not soft-removed; see
    # test_orm_relationships.py::test_user_delete_hard_deletes_own_comments_but_orphans_other_users_replies
    # for the behavior this locks in, and get a product decision before any
    # account-deletion feature changes either side of this.
    parent_id = Column(
        Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    depth = Column(Integer, nullable=False, default=0, server_default="0")

    # Editing / deletion (3A.3)
    edited_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    # Moderator removal, distinct from the author's own delete (1F.4.1 / 1I.3.1)
    removed_at = Column(DateTime, nullable=True)
    removed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    removed_reason = Column(String(255), nullable=True)

    # Automatic translation (3A.5) -- detected language of the original text.
    source_language = Column(String(16), nullable=True)

    # Cached counters (1C.3.6: comments are a high-volume table -- avoid a
    # COUNT() over comment_votes on every list query).
    like_count = Column(Integer, nullable=False, default=0, server_default="0")
    dislike_count = Column(Integer, nullable=False, default=0, server_default="0")

    # Memes/GIFs embedded in a comment (3B). attachment_type is "gif" (Tier 1,
    # URL/metadata only) or "meme" (Tier 2, our own uploaded+moderated image).
    attachment_type = Column(String(16), nullable=True)
    attachment_url = Column(String(1000), nullable=True)
    attachment_metadata = Column(JSON, nullable=True)

    user = relationship(
        "User", lazy="selectin", foreign_keys=[user_id], back_populates="comments"
    )
    removed_by = relationship("User", foreign_keys=[removed_by_id])
    parent = relationship("Comment", remote_side=[id], backref="replies")

    def to_dict(self):
        with allow_email_decryption():
            user_email = self.user.email if self.user else None
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_email": None,
            # F-78: see User.to_dict -- the argon2id email digest is not
            # client-facing, and a public comment thread is the worst place
            # to publish one.
            "user_email_masked": mask_email(user_email),
            "username": getattr(self.user, "username", None) if self.user else None,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "content": self.content,
            "parent_id": self.parent_id,
            "depth": self.depth or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "edited_at": self.edited_at.isoformat() if self.edited_at else None,
            "deleted": self.deleted_at is not None,
            "removed": self.removed_at is not None,
            "removed_reason": self.removed_reason if self.removed_at else None,
            "source_language": self.source_language,
            "like_count": self.like_count or 0,
            "dislike_count": self.dislike_count or 0,
            "attachment_type": self.attachment_type,
            "attachment_url": self.attachment_url,
            "attachment_metadata": self.attachment_metadata,
        }


class PermissionOverride(Base):
    """A per-person permission override (SRS 1F.6.2).

    ``state`` is 'granted' or 'revoked'. Absence of a row means 'inherited'
    (the role default applies). One row per (user, permission).
    """

    __tablename__ = "permission_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "permission", name="uq_permission_override"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False)  # granted | revoked
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class PermissionPreset(Base):
    """A named, PA-creatable permission preset (SRS 1F.9.3).

    ``definition`` is {"grant": [keys], "revoke": [keys]}. Built-in presets live
    in code (core.permissions.BUILTIN_PRESETS); this table holds custom ones.
    """

    __tablename__ = "permission_presets"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), nullable=False, unique=True)
    label = Column(String(120), nullable=False)
    description = Column(String(400), nullable=True)
    definition = Column(JSON, nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class RevokedToken(Base):
    """A JWT that must no longer be honoured, keyed by its ``jti``.

    Access and refresh tokens are stateless: once signed, they are valid until
    they expire, and nothing the server does can take that back. That made
    ``POST /auth/logout`` cosmetic — it cleared the browser's cookies, but a
    refresh token copied off the wire or out of a stolen profile stayed usable
    for the whole configured session length (up to 30 days).

    This is the revocation half. It is a denylist rather than an allowlist, so
    the common path (a token nobody revoked) costs one indexed lookup and the
    table stays small: rows are only written on logout, rotation, and
    administrative session revocation, and are purged once ``expires_at``
    passes, after which the token is refused on its own expiry anyway.

    ``users.sessions_revoked_before`` handles "sign out everywhere" without
    writing a row per outstanding token — any token issued before that instant
    is refused.
    """

    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token_type = Column(String(16), nullable=False)
    reason = Column(String(32), nullable=True)
    # When the token would have expired anyway. Rows past this point are dead
    # weight and are purged (see services.token_revocation.purge_expired).
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=False, server_default=func.now())
