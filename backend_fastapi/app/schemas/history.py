from typing import Optional
from pydantic import BaseModel, RootModel
from typing import List


class HistoryEntryBase(BaseModel):
    id: int
    manga_id: int
    manga_title: Optional[str] = None
    cover_image: Optional[str] = None
    chapter_id: int
    chapter_title: Optional[str] = None
    last_read_at: Optional[str] = None


class HistoryListResponse(RootModel):
    root: List[HistoryEntryBase]


class HistoryUpsertRequest(BaseModel):
    manga_id: int
    chapter_id: int


class HistoryDeleteResponse(BaseModel):
    ok: bool
    deleted_id: int


class HistoryClearResponse(BaseModel):
    ok: bool
    deleted_count: int
