"""Service for managing read history records."""

from datetime import datetime
from sqlalchemy.orm import Session
from ..models import ReadHistory, User


def record_history(
    user: User,
    manga_id: int,
    chapter_id: int,
    db: Session,
) -> tuple[ReadHistory, bool]:
    """
    Record or update a read history entry for a user, manga, and chapter.

    Returns a tuple containing the history entry and a boolean indicating
    if it was created (True) or updated (False).
    """
    now = datetime.utcnow()
    entry = (
        db.query(ReadHistory)
        .filter(ReadHistory.user_id == user.id, ReadHistory.chapter_id == chapter_id)
        .first()
    )
    if entry is not None:
        entry.manga_id = manga_id
        entry.last_read_at = now
        db.commit()
        db.refresh(entry)
        return entry, False

    entry = ReadHistory(
        user_id=user.id,
        manga_id=manga_id,
        chapter_id=chapter_id,
        last_read_at=now,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry, True
