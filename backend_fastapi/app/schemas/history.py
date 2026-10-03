"""Request and response shapes for a signed-in reader's read-chapter list."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

# One request carries at most this many chapters; the page sends bigger
# libraries in several requests.
MAX_SYNC_ENTRIES = 2000


class HistoryReadEntry(BaseModel):
    chapter_id: int
    # When the reader opened it (ISO 8601). Missing or unreadable means "now".
    read_at: Optional[str] = None


class HistorySyncRequest(BaseModel):
    """Changes to apply to the account's read chapters, in this order:
    clear everything, clear some series, then mark these chapters as read."""

    entries: List[HistoryReadEntry] = Field(default_factory=list, max_length=MAX_SYNC_ENTRIES)
    clear_manga: List[int] = Field(default_factory=list, max_length=MAX_SYNC_ENTRIES)
    clear_all: bool = False
    # False while the browser is still sending a big library in pieces.
    return_entries: bool = True


class HistoryEntry(BaseModel):
    manga_id: int
    chapter_id: int
    chapter_number: Optional[float] = None
    read_at: Optional[str] = None


class HistoryListResponse(BaseModel):
    entries: List[HistoryEntry]
