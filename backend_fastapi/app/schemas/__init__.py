"""Convenience exports for schema classes."""

from .auth import LoginRequest, RefreshRequest, TokenPair
from .user import UserBase, UserCreate, UserInDB, UserRead, UserUpdate

from .manga import (
    MangaBase,
    MangaListResponse,
    MangaDetailResponse,
    ChapterBase,
    ChapterListResponse,
    ChapterDetailResponse,
)

from .history import (
    HistoryEntryBase,
    HistoryListResponse,
    HistoryUpsertRequest,
    HistoryDeleteResponse,
    HistoryClearResponse,
)

from .admin import (
    AdminResponseBase,
    AdminActionResponse,
    AdminAuditLogEntry,
    AdminAuditLogResponse,
    AdminMangaListResponse,
    AdminScrapingJobBase,
    AdminScrapingJobResponse,
    AdminTokenBase,
    AdminTokenResponse,
    RescrapeResponse,
)

from .bookmarks import (
    BookmarkBase,
    BookmarkListResponse,
    BookmarkCreateRequest,
    BookmarkActionResponse,
)

from .comments import (
    CommentCreateRequest,
    CommentItem,
    CommentListResponse,
)

from .translation import (
    TranslationRequest,
    TranslationResponse,
    TranslationErrorResponse,
)

from .ocr import (
    OCRBox,
    OCROverlayResponse,
    OCRTranslateOverlayRequest,
)

from .user_settings import (
    UserSettingsResponse,
    UpdateUserSettingsRequest,
    UpdateUserAPIKeysResponse,
    UploadProfileImageResponse,
)


from .ad_slots import AdSlotCreate, AdSlotUpdate

from .branding import BrandingUpdateRequest, FooterUpdateRequest

from .integrations import IntegrationAddRequest, IntegrationRemoveRequest

__all__ = [
    "LoginRequest",
    "RefreshRequest",
    "TokenPair",
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserRead",
    "UserInDB",
    "MangaBase",
    "MangaListResponse",
    "MangaDetailResponse",
    "ChapterBase",
    "ChapterListResponse",
    "ChapterDetailResponse",
    "HistoryEntryBase",
    "HistoryListResponse",
    "HistoryUpsertRequest",
    "HistoryDeleteResponse",
    "HistoryClearResponse",
    "AdminResponseBase",
    "AdminActionResponse",
    "AdminAuditLogEntry",
    "AdminAuditLogResponse",
    "AdminMangaListResponse",
    "AdminScrapingJobBase",
    "AdminScrapingJobResponse",
    "AdminTokenBase",
    "AdminTokenResponse",
    "RescrapeResponse",
    "BookmarkBase",
    "BookmarkListResponse",
    "BookmarkCreateRequest",
    "BookmarkActionResponse",
    "CommentCreateRequest",
    "CommentItem",
    "CommentListResponse",
    "TranslationRequest",
    "TranslationResponse",
    "TranslationErrorResponse",
    "OCRBox",
    "OCROverlayResponse",
    "OCRTranslateOverlayRequest",
    "UserSettingsResponse",
    "UpdateUserSettingsRequest",
    "UpdateUserAPIKeysResponse",
    "UploadProfileImageResponse",
    "AdSlotCreate",
    "AdSlotUpdate",
    "BrandingUpdateRequest",
    "FooterUpdateRequest",
    "IntegrationAddRequest",
    "IntegrationRemoveRequest",
]
