"""A signed-in reader's read chapters, kept on their account.

The reader's browser stays the main copy (it works offline and for guests).
For someone who is signed in, the server also keeps *which chapters they have
opened and when* (one ``read_history`` row per account and chapter), so the
dimmed chapters and "where I stopped" follow them to a new phone. Nothing else
about their reading is stored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Chapter, ReadHistory, User

# What one sign-in may bring back (newest first).
MAX_LIST_ROWS = 50000
_CHUNK = 500


def parse_read_at(raw: str | None, now: datetime | None = None) -> datetime:
    """A client's timestamp as naive UTC, never later than now."""

    now = now or datetime.utcnow()
    if not raw:
        return now
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return now
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return min(parsed, now)


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


def mark_read(user: User, chapters: dict[int, datetime], db: Session) -> int:
    """Mark chapters read (``{chapter_id: read_at}``). Unknown chapters are
    ignored, and an older time never replaces a newer one. Returns how many
    chapters were new for the account. The caller commits."""

    created = 0
    ids = list(chapters)
    for start in range(0, len(ids), _CHUNK):
        part = ids[start : start + _CHUNK]
        manga_of = dict(db.query(Chapter.id, Chapter.manga_id).filter(Chapter.id.in_(part)))
        existing: dict[int, list[ReadHistory]] = {}
        for row in db.query(ReadHistory).filter(
            ReadHistory.user_id == user.id, ReadHistory.chapter_id.in_(part)
        ):
            existing.setdefault(row.chapter_id, []).append(row)
        for chapter_id in part:
            manga_id = manga_of.get(chapter_id)
            if manga_id is None:
                continue
            at = chapters[chapter_id]
            rows = existing.get(chapter_id)
            if rows:
                # Two devices can race and leave two rows: keep them in step.
                for row in rows:
                    if row.last_read_at is None or row.last_read_at < at:
                        row.last_read_at = at
                continue
            db.add(
                ReadHistory(
                    user_id=user.id, manga_id=manga_id, chapter_id=chapter_id, last_read_at=at
                )
            )
            created += 1
    return created


def clear_history(
    user: User, db: Session, *, manga_ids: list[int] | None = None, everything: bool = False
) -> None:
    """Forget the account's read chapters (all of them, or for some series).
    The caller commits."""

    query = db.query(ReadHistory).filter(ReadHistory.user_id == user.id)
    if everything:
        query.delete(synchronize_session=False)
    elif manga_ids:
        query.filter(ReadHistory.manga_id.in_(manga_ids)).delete(synchronize_session=False)


def list_history(user: User, db: Session) -> list[dict]:
    """The account's read chapters, one per chapter, newest first."""

    from ..models.manga import chapter_number_value

    rows = (
        db.query(ReadHistory, Chapter.chapter_number)
        .join(Chapter, ReadHistory.chapter_id == Chapter.id)
        .filter(ReadHistory.user_id == user.id)
        .order_by(ReadHistory.last_read_at.desc().nullslast(), ReadHistory.id.desc())
        .limit(MAX_LIST_ROWS)
        .all()
    )
    seen: set[int] = set()
    out: list[dict] = []
    for entry, number in rows:
        if entry.chapter_id in seen or entry.manga_id is None:
            continue
        seen.add(entry.chapter_id)
        value = chapter_number_value(number)
        out.append(
            {
                "manga_id": entry.manga_id,
                "chapter_id": entry.chapter_id,
                "chapter_number": float(value) if value is not None else None,
                "read_at": entry.last_read_at.isoformat() + "Z" if entry.last_read_at else None,
            }
        )
    return out
