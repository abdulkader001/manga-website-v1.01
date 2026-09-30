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


class ScrapedChapterSchema(BaseModel):
    source_url: str
    pages: List[str]
