from pydantic import BaseModel
from typing import List


class ChapterSchema(BaseModel):
    url: str
    title: str
    number: float


class MangaSchema(BaseModel):
    title: str
    description: str
    cover: str
    source_url: str
    chapters: List[ChapterSchema]
    # Every chapter the source lists (``chapters`` holds only the new ones on
    # a re-scrape), so the admin can see how many the source really has.
    total_chapters: int = 0
    authors: List[str] = []
    genres: List[str] = []


class ScrapedChapterSchema(BaseModel):
    source_url: str
    pages: List[str]
