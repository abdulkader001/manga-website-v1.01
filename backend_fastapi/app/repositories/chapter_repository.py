from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from ..models import Chapter


class ChapterRepository:
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_by_id(self, chapter_id: int) -> Optional[Chapter]:
        return self.db.query(Chapter).filter(Chapter.id == chapter_id).first()

    def get_by_url(self, manga_id: int, url: str) -> Optional[Chapter]:
        return (
            self.db.query(Chapter)
            .filter(Chapter.manga_id == manga_id, Chapter.chapter_url == url)
            .first()
        )

    def get_existing_chapter_numbers(self, manga_id: int) -> List[float]:
        rows = (
            self.db.query(Chapter.chapter_number)
            .filter(Chapter.manga_id == manga_id)
            .all()
        )
        return [float(r[0]) for r in rows if r[0] is not None]

    def get_urls_for_manga(self, manga_id: int) -> set[str]:
        """Every source URL already stored for the series, including the
        members of grouped chapters."""

        from ..services.chapter_grouping import known_source_urls

        rows = self.db.query(Chapter).filter(Chapter.manga_id == manga_id).all()
        return known_source_urls(rows)

    def get_unscraped_chapters(self, manga_id: int) -> List[Chapter]:
        return (
            self.db.query(Chapter)
            .filter(Chapter.manga_id == manga_id, Chapter.pages.is_(None))
            .all()
        )

    def create(self, **kwargs) -> Chapter:
        chapter = Chapter(**kwargs)
        self.db.add(chapter)
        self.db.flush()
        return chapter

    def update(self, chapter: Chapter, **kwargs) -> Chapter:
        for key, value in kwargs.items():
            setattr(chapter, key, value)
        self.db.flush()
        return chapter

    def bulk_insert(self, chapters_data: List[Dict[str, Any]]):
        if not chapters_data:
            return

        objects = [Chapter(**data) for data in chapters_data]
        self.db.bulk_save_objects(objects)
        self.db.flush()
