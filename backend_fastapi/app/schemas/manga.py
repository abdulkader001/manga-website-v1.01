from typing import List, Optional, Union
from pydantic import BaseModel, RootModel

Number = Union[int, float]


class MangaBase(BaseModel):
    id: int
    title: str
    slug: Optional[str] = None
    cover_image: Optional[str] = None
    cover_url: Optional[str] = None
    description: Optional[str] = None
    # Admin-only: omitted for readers and visitors.
    source_url: Optional[str] = None
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
    # Reader-facing presentation fields (catalogue_service).
    author: Optional[str] = None
    artist: Optional[str] = None
    authors: List[str] = []
    artists: List[str] = []
    alt_titles: List[str] = []
    mangaupdates_url: Optional[str] = None
    scrape_layout: Optional[dict] = None
    is_hot: bool = False
    views: int = 0
    views_formatted: str = "0"
    daily_views: int = 0
    weekly_views: int = 0
    monthly_views: int = 0
    rating: float = 0.0
    rating_count: int = 0
    user_rating: Optional[int] = None
    chapters_count: int = 0
    latest_chapter_number: Optional[Number] = None
    last_chapter_title: Optional[str] = None
    country: Optional[str] = None
    banner_image: Optional[str] = None
    auto_scrape_enabled: bool = True
    scrape_frequency: Optional[str] = None
    scrape_interval_value: Optional[int] = None
    scrape_interval_unit: Optional[str] = None
    next_scrape_at: Optional[str] = None
    last_scraped_at: Optional[str] = None
    ingestion_status: Optional[str] = None


class MangaListResponse(BaseModel):
    items: List[MangaBase]
    total: int
    page: int
    per_page: int
    genres: List[str]
    cache_hit: bool


class MangaDetailResponse(MangaBase):
    chapters_count: int


class ChapterBase(BaseModel):
    id: int
    number: Optional[str] = None
    chapter_number: Optional[Number] = None
    title: Optional[str] = None
    url: str
    read: bool
    created_at: Optional[str] = None
    release_date: Optional[str] = None
    views: int = 0
    likes: int = 0
    page_count: int = 0
    ingestion_status: Optional[str] = None


class ChapterListResponse(RootModel):
    root: List[ChapterBase]


class ChapterDetailResponse(BaseModel):
    id: int
    manga_id: int
    chapter_number: Optional[Number] = None
    chapter_title: Optional[str] = None
    title: Optional[str] = None
    manga_title: Optional[str] = None
    chapter_url: str
    scraped_at: Optional[str] = None
    release_date: Optional[str] = None
    views: int = 0
    likes: int = 0
    liked: bool = False
    prev_chapter_id: Optional[int] = None
    next_chapter_id: Optional[int] = None
    ingestion_status: Optional[str] = None
    pages: List[str] = []
    # Effective translation right for the parent series (SRS 1J). Lets the
    # reader skip the overlay for series not licensed for translation.
    may_translate: bool = True
