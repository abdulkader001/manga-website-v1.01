from typing import List, Optional
from pydantic import BaseModel, RootModel


class MangaBase(BaseModel):
    id: int
    title: str
    slug: Optional[str] = None
    cover_image: Optional[str] = None
    cover_url: Optional[str] = None
    description: Optional[str] = None
    source_url: str
    language: Optional[str] = None
    type: str
    status: str
    last_chapter_at: Optional[str] = None
    genres: List[str] = []
    popularity: Optional[int] = None
    last_scraped: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Content rights (SRS 1J). Exposed so the reader can hide the translate UI
    # and render the required attribution.
    may_host: bool = True
    may_translate: bool = True
    attribution: Optional[str] = None
    takedown_status: str = "none"


class MangaListResponse(BaseModel):
    items: List[MangaBase]
    total: int
    page: int
    per_page: int
    genres: List[str]
    cache_hit: bool
    secret_phrase_used: bool


class MangaDetailResponse(MangaBase):
    chapters_count: int


class ChapterBase(BaseModel):
    id: int
    number: Optional[str] = None
    title: Optional[str] = None
    url: str
    read: bool
    created_at: Optional[str] = None


class ChapterListResponse(RootModel):
    root: List[ChapterBase]


class ChapterDetailResponse(BaseModel):
    id: int
    manga_id: int
    chapter_number: Optional[str] = None
    chapter_title: Optional[str] = None
    chapter_url: str
    scraped_at: Optional[str] = None
    pages: List[str] = []
    # Effective translation right for the parent series (SRS 1J). Lets the
    # reader skip the overlay for series not licensed for translation.
    may_translate: bool = True
