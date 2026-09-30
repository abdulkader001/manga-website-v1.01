"""Bell notifications (SRS 1I).

Sub-part 1G requires several events to notify administrators (parser
candidate ready, honest generation failure, rescrape completion, structure
change alerts). Sub-part 1I is the delivery system: the bell, preferences,
and the queue-backed creation path those events (and reader-facing events)
write through.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    ForeignKey,
    func,
    Index,
    JSON,
    text,
)

from .base import Base

# reader | administrative | security (1I.4). Security is never suppressible
# regardless of a recipient's mute/preference settings (1I.3.2).
CATEGORY_READER = "reader"
CATEGORY_ADMINISTRATIVE = "administrative"
CATEGORY_SECURITY = "security"

PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITY_SECURITY = "security"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read"),
        # Partitioning key per 1I.5.4: unread-count and list queries always
        # filter by user_id first, then recency — this index keeps both off
        # a full-table scan as the table grows.
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_dedup", "user_id", "type", "dedup_key"),
    )

    id = Column(Integer, primary_key=True)
    # NULL user_id = addressed to the Permanent Administrator(s) — resolved at
    # read time so the PA binding (1F.2.3) stays the single source of truth.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Machine type, e.g. parser.candidate_ready, parser.generation_failed,
    # rescrape.completed, website.structure_changed, chapter.new
    type = Column(String(64), nullable=False)
    category = Column(
        String(16),
        nullable=False,
        default=CATEGORY_READER,
        server_default=CATEGORY_READER,
    )
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(64), nullable=True)
    data = Column(JSON, nullable=True)
    # Kept alongside read_at for the existing boolean-indexed query path;
    # the two are always written together.
    read = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    read_at = Column(DateTime, nullable=True)
    priority = Column(
        String(16),
        nullable=False,
        default=PRIORITY_NORMAL,
        server_default=PRIORITY_NORMAL,
    )
    # Batching/dedup key (1I.5.3): a second event with the same
    # (user_id, type, dedup_key) while the first is still unread updates the
    # existing row instead of creating a new one.
    dedup_key = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "category": self.category or CATEGORY_READER,
            "title": self.title,
            "body": self.body,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "data": self.data or {},
            "read": bool(self.read),
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "priority": self.priority or PRIORITY_NORMAL,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class NotificationPreference(Base):
    """Per-account notification preferences (SRS 1I.5.2), one row per user.

    ``muted_types``/``email_types``/``digest_types`` are JSON arrays of the
    machine ``type`` strings from 1I.3 — kept as arrays rather than one
    column per type so new notification types never require a migration.
    """

    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    # Mutes everything except category=security (1I.3.2, always delivered).
    global_mute = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    muted_types = Column(JSON, nullable=False, default=list)
    email_types = Column(JSON, nullable=False, default=list)
    digest_types = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self):
        return {
            "global_mute": bool(self.global_mute),
            "muted_types": list(self.muted_types or []),
            "email_types": list(self.email_types or []),
            "digest_types": list(self.digest_types or []),
        }
