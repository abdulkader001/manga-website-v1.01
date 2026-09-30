"""Generate simple manga suggestions based on bookmarks and history."""

from __future__ import annotations

import structlog
from typing import Dict, List, Set

from ..core.db import SessionLocal
from ..models import Bookmark, Manga, ReadHistory

logger = structlog.get_logger(__name__)


class SuggestionsService:
    """Recommend manga by overlapping genres from user activity."""

    def get_recommendations(self, user_id: int, limit: int = 10) -> List[Dict]:
        try:
            session = SessionLocal()
            try:
                genres: List[str] = []
                bookmarked = session.query(Bookmark).filter_by(user_id=user_id).all()
                history = session.query(ReadHistory).filter_by(user_id=user_id).all()

                user_manga_ids: Set[int] = {
                    *[b.manga_id for b in bookmarked],
                    *[h.manga_id for h in history],
                }

                if user_manga_ids:
                    mangas = (
                        session.query(Manga).filter(Manga.id.in_(user_manga_ids)).all()
                    )
                    for manga in mangas:
                        if manga.genres:
                            genres.extend(
                                [g.lower().strip() for g in manga.genres if g]
                            )

                if not genres:
                    return []

                query = (
                    session.query(Manga)
                    .filter(Manga.genres.overlap(genres))
                    .filter(~Manga.id.in_(user_manga_ids))
                    .limit(limit)
                    .all()
                )
                return [m.to_dict() for m in query]
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to generate recommendations: %s", exc, exc_info=True)
            return []


__all__ = ["SuggestionsService"]
