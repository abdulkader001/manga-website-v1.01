from typing import Optional
from sqlalchemy.orm import Session
from ..models import Manga


class MangaRepository:
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_by_url(self, url: str) -> Optional[Manga]:
        return self.db.query(Manga).filter(Manga.source_url == url).first()

    def get_by_id(self, manga_id: int) -> Optional[Manga]:
        return self.db.query(Manga).filter(Manga.id == manga_id).first()

    def create(self, **kwargs) -> Manga:
        manga = Manga(**kwargs)
        self.db.add(manga)
        self.db.flush()
        return manga

    def update(self, manga: Manga, **kwargs) -> Manga:
        for key, value in kwargs.items():
            setattr(manga, key, value)
        self.db.flush()
        return manga
