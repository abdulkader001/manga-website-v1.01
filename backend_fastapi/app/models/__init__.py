# -----------------------------------------------------------------------------
# Re-export all models for Alembic Base and existing imports
# -----------------------------------------------------------------------------

from .base import Base, metadata as metadata

# User and Authentication models
from .user import (
    UserRole as UserRole,
    User as User,
    LoginToken as LoginToken,
    UserAPIKey as UserAPIKey,
    Complaint as Complaint,
    Comment as Comment,
    PermissionOverride as PermissionOverride,
    PermissionPreset as PermissionPreset,
    RevokedToken as RevokedToken,
)

# Manga models
from .manga import (
    Manga as Manga,
    Chapter as Chapter,
    ReadHistory as ReadHistory,
    Bookmark as Bookmark,
)

# Scraping models
from .scraping import (
    Source as Source,
    ApprovedSourceDomain as ApprovedSourceDomain,
    ScrapingJob as ScrapingJob,
    ParserVersion as ParserVersion,
)

# Notifications (1G events + reader events; delivery UX is 1I)
from .notifications import (
    Notification as Notification,
    NotificationPreference as NotificationPreference,
)

# Shared OCR/translation cache (1H.14)
from .translation_cache import (
    OcrCache as OcrCache,
    TranslationCache as TranslationCache,
)

# Per-user processing preferences (Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2)
from .processing_settings import (
    UserProcessingSettings as UserProcessingSettings,
)

# Multi-provider admin management (Part 2: 2D)
from .provider_management import (
    SystemProviderInstance as SystemProviderInstance,
)

# Per-series character-name glossary (Part 2: 2C.1)
from .glossary import (
    SeriesGlossaryTerm as SeriesGlossaryTerm,
)

# Native community system: reactions, moderation, reputation, cultivation
# ranking (Part 3)
from .community import (
    CommentVote as CommentVote,
    CommentReaction as CommentReaction,
    ContentReport as ContentReport,
    CommentTranslation as CommentTranslation,
    CustomEmoji as CustomEmoji,
    ReputationEvent as ReputationEvent,
    Pill as Pill,
    CultivationRealmConfig as CultivationRealmConfig,
    MemeUpload as MemeUpload,
)

# Settings and Admin models
from .settings import (
    FooterSettings as FooterSettings,
    Setting as Setting,
    AdSlot as AdSlot,
    GlobalAdProvider as GlobalAdProvider,
    AdClick as AdClick,
    AdminBootstrapState as AdminBootstrapState,
    SystemState as SystemState,
    SystemSettings as SystemSettings,
    ProviderCredentials as ProviderCredentials,
    AdminPromotionToken as AdminPromotionToken,
    AdminAuditLog as AdminAuditLog,
    VaultSecret as VaultSecret,
)

# Reader engagement: ratings, likes, broken-chapter reports, announcements,
# per-day view counters
from .engagement import (
    MangaRating as MangaRating,
    ChapterLike as ChapterLike,
    ChapterReport as ChapterReport,
    Announcement as Announcement,
    MangaDailyView as MangaDailyView,
    AdminTaskResult as AdminTaskResult,
)
