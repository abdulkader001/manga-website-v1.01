"""Native community system: reactions, moderation, reputation, cultivation
ranking (SRS Part 3). ``Comment`` and ``User`` themselves stay in
``models/user.py``; this module holds the tables built on top of them.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)

from .base import Base

# ---------------------------------------------------------------------------
# 3A.3 engagement: likes/dislikes and emoji reactions
# ---------------------------------------------------------------------------


class CommentVote(Base):
    """One like/dislike per (comment, user). ``value`` is +1 or -1."""

    __tablename__ = "comment_votes"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_vote_user"),
    )

    id = Column(Integer, primary_key=True)
    comment_id = Column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    value = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class CommentReaction(Base):
    """Emoji reaction on someone else's comment (3A.4.3), Discord/Slack-style.

    A user may react to the same comment with several different emojis, but
    only once each — the unique constraint is per (comment, user, emoji).
    """

    __tablename__ = "comment_reactions"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", "emoji", name="uq_comment_reaction"),
    )

    id = Column(Integer, primary_key=True)
    comment_id = Column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Unicode emoji character, or "custom:<shortcode>" for admin-added emojis.
    emoji = Column(String(64), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 3A.3 reporting -- shared queue for both comments and memes (3B.4)
# ---------------------------------------------------------------------------

REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_ACTIONED = "actioned"
REPORT_STATUS_DISMISSED = "dismissed"
REPORT_TARGET_COMMENT = "comment"
REPORT_TARGET_MEME = "meme"


class ContentReport(Base):
    """A report against a comment or a meme upload, feeding the moderator
    queue (1F.4.1). Kept generic (target_type/target_id) so image reports
    (3B.4) reuse the same queue as comment reports."""

    __tablename__ = "content_reports"
    __table_args__ = (
        Index("ix_content_reports_status", "status"),
        Index("ix_content_reports_target", "target_type", "target_id"),
    )

    id = Column(Integer, primary_key=True)
    target_type = Column(String(16), nullable=False)
    target_id = Column(Integer, nullable=False)
    # NULL reporter_id = system-generated (3A.3: automated spam/abuse filter
    # flags a comment into the same queue a human report would).
    reporter_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    reason = Column(String(255), nullable=True)
    status = Column(
        String(16),
        nullable=False,
        default=REPORT_STATUS_PENDING,
        server_default=REPORT_STATUS_PENDING,
    )
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 3A.5 automatic comment translation -- shared/cached like manga (1H.14)
# ---------------------------------------------------------------------------


class CommentTranslation(Base):
    """Cached translation of one comment into one target language, shared
    across every reader reading in that language (3A.5)."""

    __tablename__ = "comment_translations"
    __table_args__ = (
        UniqueConstraint(
            "comment_id", "target_lang", name="uq_comment_translation_lang"
        ),
    )

    id = Column(Integer, primary_key=True)
    comment_id = Column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    target_lang = Column(String(16), nullable=False)
    translated_content = Column(Text, nullable=False)
    provider = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    last_accessed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# 3A.4.4 administrator-managed custom emojis
# ---------------------------------------------------------------------------


class CustomEmoji(Base):
    """Admin-added emoji, uploaded as an image with a keyboard shortcode
    (3A.4.4). The base Unicode set (``emoji_catalogue.py``) is never stored
    here and can never be removed."""

    __tablename__ = "custom_emojis"

    id = Column(Integer, primary_key=True)
    # Stored without colons; ":shortcode:" is a display/input convention.
    shortcode = Column(String(64), unique=True, nullable=False)
    image_url = Column(String(500), nullable=False)
    category = Column(
        String(50), nullable=False, default="custom", server_default="custom"
    )
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 3C reputation
# ---------------------------------------------------------------------------


class ReputationEvent(Base):
    """Audit trail for every reputation change (3C.2 anti-abuse, revocation).

    Reputation is never edited directly -- ``User.reputation`` is a running
    total of ``sum(delta)`` over non-revoked events. Revoking an event (e.g.
    the underlying comment was removed) subtracts its delta back out.
    """

    __tablename__ = "reputation_events"
    __table_args__ = (Index("ix_reputation_events_user", "user_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    delta = Column(Integer, nullable=False)
    source = Column(String(50), nullable=False)
    ref_type = Column(String(32), nullable=True)
    ref_id = Column(String(64), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 3C.3 Pills -- cache-sharing reward
# ---------------------------------------------------------------------------

PILL_STATUS_UNCLAIMED = "unclaimed"
PILL_STATUS_CLAIMED = "claimed"
PILL_STATUS_REVOKED = "revoked"
PILL_REPUTATION_VALUE = 100


class Pill(Base):
    """One Pill per (user, chapter, language) -- minted only when that
    user's shared translation is the accepted (non-superseded) version
    (3C.3.3). Unclaimed Pills never expire."""

    __tablename__ = "pills"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "chapter_id", "target_lang", name="uq_pill_user_chapter_lang"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id = Column(
        Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    target_lang = Column(String(16), nullable=False)
    status = Column(
        String(16),
        nullable=False,
        default=PILL_STATUS_UNCLAIMED,
        server_default=PILL_STATUS_UNCLAIMED,
    )
    claimed_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 3D cultivation ranking system
# ---------------------------------------------------------------------------


class CultivationRealmConfig(Base):
    """One realm in the progression (3D.2). Names, thresholds, color band,
    and the "dedicated contributor" cutoff (3D.5) are all administrator
    configurable -- never hardcoded in application logic.

    ``dedicated_contributor`` is informational only: it marks realms whose
    members are recognizable as sustained contributors. There is no
    automated queue logic attached to it -- a moderator or administrator who
    is asked directly to prioritize a request decides that by hand, using
    the requester's visible rank as context.
    """

    __tablename__ = "cultivation_realms"
    __table_args__ = (UniqueConstraint("order_index", name="uq_realm_order"),)

    id = Column(Integer, primary_key=True)
    order_index = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    stage_count = Column(Integer, nullable=False, default=10, server_default="10")
    # Reputation required to ENTER this realm (its stage 1).
    reputation_threshold = Column(Integer, nullable=False)
    # gray | gold | sparkling_gold | diamond | purple (3E.2 band, styling is
    # the frontend's job -- this just names which band).
    color_band = Column(
        String(30), nullable=False, default="gray", server_default="gray"
    )
    # SRS 3D.5: realms at/above this flag are recognizable as dedicated
    # contributors -- informational for a moderator/administrator's own
    # judgment call, not wired to any automated queue behavior.
    dedicated_contributor = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# 3B.2 Tier 2 -- user-uploaded memes
# ---------------------------------------------------------------------------


class MemeUpload(Base):
    """A user-uploaded meme image (Tier 2, 3B.2). Stored converted to WebP;
    ``content_hash`` is the dedup key (3B.4 -- one image stored once)."""

    __tablename__ = "meme_uploads"

    id = Column(Integer, primary_key=True)
    uploader_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content_hash = Column(String(64), unique=True, nullable=False)
    url = Column(String(500), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    byte_size = Column(Integer, nullable=True)
    removed_at = Column(DateTime, nullable=True)
    removed_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


__all__ = [
    "CommentVote",
    "CommentReaction",
    "ContentReport",
    "REPORT_STATUS_PENDING",
    "REPORT_STATUS_ACTIONED",
    "REPORT_STATUS_DISMISSED",
    "REPORT_TARGET_COMMENT",
    "REPORT_TARGET_MEME",
    "CommentTranslation",
    "CustomEmoji",
    "ReputationEvent",
    "Pill",
    "PILL_STATUS_UNCLAIMED",
    "PILL_STATUS_CLAIMED",
    "PILL_STATUS_REVOKED",
    "PILL_REPUTATION_VALUE",
    "CultivationRealmConfig",
    "MemeUpload",
]
