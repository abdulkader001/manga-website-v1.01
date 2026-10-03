"""New-chapter alerts for readers who bookmarked a series.

A signed-in reader's bookmarks are kept on the server as series ids only
(``bookmarks`` rows; reading history stays in the browser), so this is where
the "who follows this series" list comes from. Guests' bookmarks live in their
browser alone and get no alerts.

Called wherever new chapters of an existing series are added: the scheduled
new-chapter check and a scrape job run on a series that already exists.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session


def followers_of(db: Session, manga_id: int) -> list[int]:
    from ..models import Bookmark

    rows = (
        db.query(Bookmark.user_id)
        .filter(Bookmark.manga_id == manga_id)
        .distinct()
        .all()
    )
    return sorted(row[0] for row in rows)


def notify_followers_of_new_chapters(db: Session, manga, chapter_numbers: Iterable) -> int:
    """Tell every reader who bookmarked ``manga`` about its newest chapter.

    Returns how many readers were notified. Never raises: an alert must not
    fail the scrape that found the chapters.
    """

    numbers = [float(n) for n in chapter_numbers if n is not None]
    if not numbers:
        return 0
    from .notification_service import notify_async

    latest = max(numbers)
    label = f"{latest:g}"  # 12.0 -> "12", 12.5 -> "12.5"
    message = f"Chapter {label} of {manga.title} is available"
    followers = followers_of(db, manga.id)
    for user_id in followers:
        # dedup_key scopes batching to this series: several new-chapter
        # events for the same series within the batch window collapse into
        # one notification (1I.5.3), while different series stay distinct.
        notify_async(
            type="chapter.new",
            title=message,
            body=message,
            user_id=user_id,
            data={"series_id": manga.id, "chapter_number": latest},
            target_type="series",
            target_id=manga.id,
            dedup_key=f"chapter.new:{manga.id}",
        )
    return len(followers)


__all__ = ["followers_of", "notify_followers_of_new_chapters"]
