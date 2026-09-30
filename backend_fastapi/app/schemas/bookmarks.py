from typing import List, Optional
from pydantic import BaseModel, RootModel


class BookmarkBase(BaseModel):
    id: int
    manga_id: int
    manga_title: Optional[str] = None
    cover_image: Optional[str] = None
    chapter_id: Optional[int] = None
    chapter_title: Optional[str] = None
    created_at: Optional[str] = None


class BookmarkListResponse(RootModel):
    root: List[BookmarkBase]


class BookmarkCreateRequest(BaseModel):
    manga_id: Optional[int] = None
    mangaId: Optional[int] = None
    chapter_id: Optional[int] = None
    chapterId: Optional[int] = None


class BookmarkActionResponse(BaseModel):
    message: str
    id: Optional[int] = None
    count: Optional[int] = None
