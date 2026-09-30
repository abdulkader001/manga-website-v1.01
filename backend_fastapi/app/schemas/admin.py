from .manga import MangaBase
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, RootModel


class AdminResponseBase(BaseModel):
    message: str
    user: dict


class AdminActionResponse(BaseModel):
    ok: bool
    count: Optional[int] = None
    deleted_chapters: Optional[int] = None
    manga_id: Optional[int] = None


class AdminAuditLogEntry(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_email_masked: Optional[str] = None
    operator: Optional[str] = None
    action: str
    metadata: Optional[Any] = None
    source_ip: Optional[str] = None
    timestamp: str


class AdminAuditLogResponse(RootModel):
    root: List[AdminAuditLogEntry]


class AdminAuditLogPage(BaseModel):
    """Searchable, filterable, paginated audit log listing (SRS 1H.7.2)."""

    items: List[AdminAuditLogEntry]
    total: int
    page: int
    per_page: int
    pages: int


class AdminMangaListResponse(RootModel):
    root: List[MangaBase]


class AdminScrapingJobBase(BaseModel):
    id: int
    source_id: Optional[str] = None
    manga_id: Optional[int] = None
    source_url: Optional[str] = None
    status: str
    error: Optional[str] = None
    last_chapter_number: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminScrapingJobResponse(RootModel):
    root: List[AdminScrapingJobBase]


class AdminTokenBase(BaseModel):
    id: int
    token_hash: Optional[str] = None
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    issued_to_email: Optional[str] = None
    redeemed_by_email: Optional[str] = None


class AdminTokenResponse(RootModel):
    root: List[AdminTokenBase]


class RescrapeResponse(BaseModel):
    ok: bool
    result: dict
    manga_id: Optional[int] = None
    chapter_id: Optional[int] = None
    delete_previous: Optional[bool] = None
    message: Optional[str] = None


class AdminUsersResponse(BaseModel):
    items: List[dict]
    page: int
    pages: int
    per_page: int
    total: int
    has_next: bool
    has_prev: bool


class RoleToggleResponse(BaseModel):
    success: Optional[bool] = None
    message: Optional[str] = None
    user: dict


class AdminDomainResponse(BaseModel):
    id: int
    domain: str
    base_url: str
    label: Optional[str] = None
    # Website lifecycle + record fields (SRS 1G.1.1 / 1G.6.3)
    status: Optional[str] = None
    original_languages: Optional[List[str]] = None
    approved_by: Optional[int] = None
    approved_at: Optional[str] = None
    request_rate_limit: Optional[int] = None
    last_health_check: Optional[str] = None
    # Content rights (SRS 1J)
    may_host: Optional[bool] = None
    may_translate: Optional[bool] = None
    attribution: Optional[str] = None
    license: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminDomainDeleteResponse(BaseModel):
    ok: bool
    deleted: int


class AdSlotConfigModel(BaseModel):
    network: str = ""
    api_url: str = ""


class AdsConfigPayload(BaseModel):
    global_: Optional[AdSlotConfigModel] = Field(None, alias="global")
    header_rows: Optional[List[AdSlotConfigModel]] = None
    footer_rows: Optional[List[AdSlotConfigModel]] = None


class AdsConfigResponse(BaseModel):
    global_: AdSlotConfigModel = Field(alias="global")
    header_rows: List[AdSlotConfigModel]
    footer_rows: List[AdSlotConfigModel]


class AdminStatusResponse(BaseModel):
    authenticated: bool
    user: dict


class AdminSettingsResponse(RootModel):
    root: Dict[str, bool]
