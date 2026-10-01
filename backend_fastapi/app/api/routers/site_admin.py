"""Admin console endpoints for the v1.01 panel: social links, announcements,
chapter-report triage, auto-ad networks, site settings + maintenance,
API provider registry, audit report and scrape schedules."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import psutil
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, text
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import (
    require_admin_user,
    require_main_admin_user,
    require_permission,
)
from ...models import (
    Announcement,
    Chapter,
    ChapterReport,
    GlobalAdProvider,
    Manga,
    MangaDailyView,
    MangaRating,
    ReadHistory,
    SystemSettings,
    User,
)
from ...models.manga import format_count
from ...services import site_content_service as content
from ...utils.audit_logger import log_admin_action
from ...utils.cache_invalidation import ainvalidate_manga_caches
from ...utils.sanitizer import strip_all_html
from .reader import announcement_to_dict, report_to_dict

logger = structlog.get_logger("backend_fastapi.site_admin")

router = APIRouter(tags=["site-admin"])

PROCESS_STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Social links
# ---------------------------------------------------------------------------


class SocialLinksPayload(BaseModel):
    links: List[Dict[str, Any]] = Field(default_factory=list, max_length=30)


@router.get("/social-links")
def list_social_links(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"links": content.get_social_links(db)}


@router.post("/social-links")
def save_social_links(
    payload: SocialLinksPayload,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    return {"success": True, "links": content.replace_social_links(db, payload.links)}


@router.post("/social-links/add", status_code=status.HTTP_201_CREATED)
def add_social_link(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    link = content.normalize_social_link({**payload, "id": None})
    if link is None:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Social links must use an https:// or mailto: address.",
            field="url",
        )
    links = content.get_social_links(db) + [link]
    saved = content.replace_social_links(db, links)
    return {"success": True, "link": saved[-1], "links": saved}


@router.put("/social-links/{link_id}")
@router.patch("/social-links/{link_id}")
def update_social_link(
    link_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    links = content.get_social_links(db)
    for index, existing in enumerate(links):
        if existing["id"] == link_id:
            updated = content.normalize_social_link({**existing, **payload}, link_id=link_id)
            if updated is None:
                raise ApiError(
                    ErrorCode.VALIDATION_FAILED,
                    "Social links must use an https:// or mailto: address.",
                    field="url",
                )
            links[index] = updated
            saved = content.replace_social_links(db, links)
            return {"success": True, "link": updated, "links": saved}
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Social link not found")


@router.delete("/social-links/{link_id}")
def delete_social_link(
    link_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    links = [link for link in content.get_social_links(db) if link["id"] != link_id]
    return {"success": True, "links": content.replace_social_links(db, links)}


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


class BroadcastPayload(BaseModel):
    title: str = Field("Announcement", max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    type: str = Field("info", max_length=32)
    isPopup: bool = False


@router.post("/admin/broadcast", status_code=status.HTTP_201_CREATED)
def broadcast_announcement(
    request: Request,
    payload: BroadcastPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("broadcast")),
) -> Dict[str, Any]:
    kind = strip_all_html(payload.type).strip().lower()[:32] or "info"
    item = Announcement(
        title=strip_all_html(payload.title).strip()[:200] or "Announcement",
        message=strip_all_html(payload.message).strip(),
        type=kind,
        is_popup=payload.isPopup,
        enabled=True,
        created_by=current_user.id,
    )
    if not item.message:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Announcement text is required.", field="message")
    if payload.isPopup:
        # Only one popup is shown at a time: the newest.
        db.query(Announcement).filter(Announcement.is_popup.is_(True)).update(
            {Announcement.is_popup: False}
        )
    db.add(item)
    db.commit()
    db.refresh(item)
    log_admin_action(
        db, request, current_user, "ANNOUNCEMENT_CREATE", "announcement", str(item.id), "success"
    )
    try:
        from ...tasks.notification_tasks import fan_out_announcement

        fan_out_announcement.delay(item.id)
    except Exception:  # broker outage: the homepage still shows it
        logger.warning("announcement_fan_out_enqueue_failed", announcement_id=item.id)
    return {"success": True, "announcement": announcement_to_dict(item)}


@router.delete("/admin/announcements/{announcement_id}")
def delete_announcement(
    request: Request,
    announcement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("broadcast")),
) -> Dict[str, Any]:
    item = db.get(Announcement, announcement_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    db.delete(item)
    db.commit()
    log_admin_action(
        db, request, current_user, "ANNOUNCEMENT_DELETE", "announcement", str(announcement_id), "success"
    )
    return {"success": True}


# ---------------------------------------------------------------------------
# Chapter report triage
# ---------------------------------------------------------------------------


@router.get("/reports/chapters")
def list_chapter_reports(
    status_filter: str = Query("all", alias="status"),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("handle_reports")),
) -> Dict[str, Any]:
    query = db.query(ChapterReport)
    if status_filter in {"open", "investigating", "pending"}:
        query = query.filter(ChapterReport.status == "open")
    elif status_filter == "resolved":
        query = query.filter(ChapterReport.status == "resolved")
    reports = query.order_by(ChapterReport.created_at.desc()).limit(limit).all()
    pending = db.query(func.count(ChapterReport.id)).filter(ChapterReport.status == "open").scalar() or 0
    items = []
    for report in reports:
        row = report_to_dict(report, db)
        row["user_name"] = row.get("reporter")
        row["status"] = "resolved" if report.status == "resolved" else "investigating"
        items.append(row)
    return {"items": items, "pending_count": int(pending)}


def _get_report(db: Session, report_id: int) -> ChapterReport:
    report = db.get(ChapterReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


@router.post("/reports/{report_id}/resolve")
def resolve_chapter_report(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("handle_reports")),
) -> Dict[str, Any]:
    report = _get_report(db, report_id)
    # Resolving one report closes every open report on the same chapter: the
    # alert banner is per chapter, not per reporter.
    db.query(ChapterReport).filter(
        ChapterReport.chapter_id == report.chapter_id, ChapterReport.status == "open"
    ).update(
        {
            ChapterReport.status: "resolved",
            ChapterReport.resolved_by: current_user.id,
            ChapterReport.resolved_at: datetime.utcnow(),
        }
    )
    db.commit()
    log_admin_action(db, request, current_user, "CHAPTER_REPORT_RESOLVE", "chapter_report", str(report_id), "success")
    return {"success": True}


@router.delete("/reports/{report_id}")
def delete_chapter_report(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("handle_reports")),
) -> Dict[str, Any]:
    report = _get_report(db, report_id)
    db.delete(report)
    db.commit()
    log_admin_action(db, request, current_user, "CHAPTER_REPORT_DELETE", "chapter_report", str(report_id), "success")
    return {"success": True}


@router.post("/admin/reports/{report_id}/rescrape-single")
def rescrape_reported_chapter(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rescrape_chapter")),
) -> Dict[str, Any]:
    report = _get_report(db, report_id)
    chapter = db.get(Chapter, report.chapter_id)
    if chapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
    if chapter.manga is not None:
        from ...services.content_rights import assert_series_hostable

        assert_series_hostable(db, chapter.manga)

    from ...services.rescrape_service import fix_chapter

    result = fix_chapter(db, chapter, actor_id=current_user.id, force=True)
    log_admin_action(
        db, request, current_user, "FIX_CHAPTER", "chapter", str(chapter.id), result.get("status", "unknown")
    )
    return {
        "success": True,
        "result": result,
        "message": result.get("message")
        or "Re-scrape queued. You'll be notified when the chapter's pages are refreshed.",
    }


# ---------------------------------------------------------------------------
# Auto-ad networks
# ---------------------------------------------------------------------------


class AdNetworkPayload(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    publisher_id: Optional[str] = Field(None, max_length=120)
    script_code: Optional[str] = Field(None, max_length=20000)
    fallback_ad_url: Optional[str] = Field(None, max_length=500)
    fallback_link: Optional[str] = Field(None, max_length=500)
    enabled: Optional[bool] = None


def _network_to_dict(provider: GlobalAdProvider) -> Dict[str, Any]:
    config = dict(provider.config or {})
    return {
        "id": provider.id,
        "name": provider.name,
        "publisher_id": config.get("publisher_id", ""),
        "script_code": config.get("script_code", ""),
        "fallback_ad_url": config.get("fallback_ad_url", ""),
        "fallback_link": config.get("fallback_link", ""),
        "enabled": bool(config.get("enabled", True)),
        "impressions": int(config.get("impressions", 0)),
        "clicks": int(config.get("clicks", 0)),
    }


def _apply_network(provider: GlobalAdProvider, payload: AdNetworkPayload) -> None:
    from ...utils.sanitizer import sanitize_ad_html

    config = dict(provider.config or {})
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        provider.name = strip_all_html(data["name"]).strip()[:100]
    if "publisher_id" in data:
        config["publisher_id"] = strip_all_html(data["publisher_id"] or "").strip()
    if "script_code" in data:
        config["script_code"] = sanitize_ad_html(data["script_code"] or "")
    for key in ("fallback_ad_url", "fallback_link"):
        if key in data:
            value = (data[key] or "").strip()
            config[key] = value if value.startswith(("https://", "http://")) else ""
    if "enabled" in data and data["enabled"] is not None:
        config["enabled"] = bool(data["enabled"])
    provider.config = config


@router.get("/ads/global-networks")
def list_ad_networks(
    db: Session = Depends(get_db), _: User = Depends(require_admin_user)
) -> List[Dict[str, Any]]:
    return [_network_to_dict(p) for p in db.query(GlobalAdProvider).order_by(GlobalAdProvider.id)]


@router.post("/ads/global-networks", status_code=status.HTTP_201_CREATED)
def create_ad_network(
    payload: AdNetworkPayload,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    name = strip_all_html(payload.name or "").strip()[:100] or "Auto-Ads Network"
    if db.query(GlobalAdProvider).filter(GlobalAdProvider.name == name).first():
        raise ApiError(ErrorCode.CONFLICT, f'An ad network named "{name}" already exists.', field="name")
    provider = GlobalAdProvider(name=name, config={"enabled": True, "impressions": 0, "clicks": 0})
    _apply_network(provider, payload)
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return {"success": True, "network": _network_to_dict(provider)}


@router.patch("/ads/global-networks/{network_id}")
def update_ad_network(
    network_id: int,
    payload: AdNetworkPayload,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    provider = db.get(GlobalAdProvider, network_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found")
    _apply_network(provider, payload)
    db.commit()
    return {"success": True, "network": _network_to_dict(provider)}


@router.delete("/ads/global-networks/{network_id}")
def delete_ad_network(
    network_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    provider = db.get(GlobalAdProvider, network_id)
    if provider is not None:
        for slot in list(provider.slots or []):
            slot.provider_id = None
        db.delete(provider)
        db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Site settings & maintenance
# ---------------------------------------------------------------------------


def _session_days(db: Session) -> int:
    row = db.get(SystemSettings, 1)
    return int(row.session_expiry_days) if row is not None and row.session_expiry_days else 14


def site_settings_payload(db: Session) -> Dict[str, Any]:
    from .branding import _load_branding

    settings = content.get_site_settings(db)
    settings["session_timeout_days"] = _session_days(db)
    branding = _load_branding(db)
    settings["site_name"] = branding.get("name") or ""
    settings["tagline"] = branding.get("tagline") or ""
    settings["logo_url"] = branding.get("logo") or ""
    settings["cache_status"] = "Active (Healthy)"
    return {
        "settings": settings,
        "branding": {
            "name": branding.get("name") or "",
            "tagline": branding.get("tagline") or "",
            "logo_url": branding.get("logo") or "",
            "logo": branding.get("logo") or "",
        },
    }


@router.post("/admin/settings")
def update_site_settings(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    content.update_site_settings(db, payload)
    if payload.get("session_timeout_days") not in (None, ""):
        try:
            days = max(1, min(30, int(payload["session_timeout_days"])))
        except (TypeError, ValueError):
            raise ApiError(ErrorCode.VALIDATION_FAILED, "Session length must be 1-30 days.", field="session_timeout_days")
        row = db.get(SystemSettings, 1)
        if row is None:
            row = SystemSettings(id=1)
            db.add(row)
        row.session_expiry_days = days
    db.commit()
    from ...services.maintenance import invalidate_maintenance_cache

    invalidate_maintenance_cache()
    log_admin_action(
        db, request, current_user, "SITE_SETTINGS_UPDATE", "site_settings", "1", "success",
        new_value=str(sorted(k for k in payload.keys())),
    )
    return {"success": True, "message": "Settings saved.", **site_settings_payload(db)}


@router.post("/admin/settings/clear-cache")
async def clear_site_cache(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None))
    log_admin_action(db, request, current_user, "CACHE_CLEAR", "cache", "manga", "success")
    return {"success": True, "message": "Catalogue caches cleared. Pages will refresh on next load."}


class ConfirmPayload(BaseModel):
    confirm: Optional[str] = None


@router.post("/admin/maintenance/delete-all-manga")
async def delete_all_manga(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...dependencies.auth import is_main_admin

    if not is_main_admin(current_user):
        raise ApiError(ErrorCode.FORBIDDEN, "Only the main administrator can do this.")
    count = db.query(func.count(Manga.id)).scalar() or 0
    for manga in db.query(Manga).all():
        db.delete(manga)
    db.commit()
    from ...services import page_image_service

    page_image_service.delete_all_files()
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None))
    log_admin_action(
        db, request, current_user, "CATALOG_PURGE", "manga", "*", "success", previous_value=str(count)
    )
    return {"success": True, "deleted": int(count), "message": f"Deleted {count} series and all their chapters."}


@router.post("/admin/maintenance/purge-all-images")
async def purge_all_images(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Drop cached OCR/translation results and catalogue caches. Stored page
    URLs are untouched, so chapters stay readable."""

    from ...models import OcrCache, TranslationCache

    ocr = db.query(OcrCache).delete(synchronize_session=False)
    translations = db.query(TranslationCache).delete(synchronize_session=False)
    db.commit()
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None))
    log_admin_action(db, request, current_user, "IMAGE_CACHE_PURGE", "cache", "images", "success")
    return {
        "success": True,
        "message": f"Purged {ocr} cached OCR results and {translations} cached translations.",
    }


# ---------------------------------------------------------------------------
# API provider registry (maps onto the multi-provider system, SRS 2D)
# ---------------------------------------------------------------------------

REGISTRY_CATEGORIES = ("ocr", "ai", "translation")


def _mask(secret: Optional[str]) -> str:
    if not secret:
        return ""
    if len(secret) <= 10:
        return "••••••••"
    return f"{secret[:4]}••••••••{secret[-4:]}"


def _is_masked(value: Optional[str]) -> bool:
    return bool(value) and "•" in value


def _vault_fns(request: Request):
    vault = getattr(request.app.state, "integration_key_vault", None)
    encrypt = getattr(vault, "encrypt", None)
    decrypt = getattr(vault, "decrypt", None)
    return (
        encrypt if callable(encrypt) else (lambda v: v),
        decrypt if callable(decrypt) else (lambda v: v),
    )


def _registry_entry(record, decrypt) -> Dict[str, Any]:
    config = dict(record.config or {})
    try:
        plain = decrypt(record.api_key) if record.api_key else None
    except Exception:
        plain = None
    return {
        "id": record.provider_id,
        "pk": record.id,
        "label": record.provider_name,
        "apiKey": _mask(plain),
        "hasKey": bool(record.api_key),
        "defaultUrl": record.api_url or "",
        "defaultModel": config.get("model", ""),
        "description": config.get("description", ""),
        "enabled": record.status != "disabled",
        "status": record.status,
        "priority": record.priority,
        "isCustom": True,
        "category": record.service,
        "requiresKey": bool(record.api_key),
        "allowsUrl": bool(record.api_url),
        "allowsModel": bool(config.get("model")),
    }


def _find_provider(db: Session, category: str, provider_id: str):
    from ...models.provider_management import SystemProviderInstance

    slug = (provider_id or "").strip().lower()
    return (
        db.query(SystemProviderInstance)
        .filter(
            SystemProviderInstance.service == category,
            (SystemProviderInstance.provider_id == slug)
            | (func.lower(SystemProviderInstance.provider_name) == slug),
        )
        .order_by(SystemProviderInstance.id)
        .first()
    )


def site_default_engines(db: Session) -> List[Dict[str, Any]]:
    """The engines every reader falls back to until they add their own.

    A reader who saves their own OCR / translation / AI provider overrides the
    matching default for their account (see services.processing_plan), so
    these only serve readers who have configured nothing.
    """

    from ...models.provider_management import SystemProviderInstance
    from ...services.ocr_service import tesseract_langs_installed
    from ...services.provider_resolver import env_translation_config
    from ...services.system_settings_service import get_or_create_system_settings

    settings_row = get_or_create_system_settings(db)
    langs = tesseract_langs_installed()
    ocr_ready = bool(settings_row.local_ocr_enabled) and bool(langs)
    translator = env_translation_config()
    configured_ocr = db.query(SystemProviderInstance).filter_by(service="ocr", status="active").count()
    configured_tr = db.query(SystemProviderInstance).filter_by(service="translation", status="active").count()
    return [
        {
            "service": "ocr",
            "id": "tesseract_server",
            "label": "Tesseract (built in)",
            "where": "server",
            "active": ocr_ready,
            "detail": (
                "Reads Korean, Japanese, Chinese and English on our server. "
                + ("Languages installed: " + ", ".join(sorted(langs)) + "." if langs else "Tesseract is not installed in this image: rebuild the backend (GUIDE.md 4.1).")
                + ("" if settings_row.local_ocr_enabled else " Switched off: turn on local OCR in Admin Settings or set OCR_ENABLED in the Secret Vault.")
            ),
            "overridden_by_reader": True,
        },
        {
            "service": "ocr",
            "id": "ppocr_browser",
            "label": "PP-OCR (in the reader's browser)",
            "where": "browser",
            "active": False,
            "detail": "Not active: the browser OCR models are not hosted yet, so nothing is downloaded. Server Tesseract is used meanwhile.",
            "overridden_by_reader": True,
        },
        {
            "service": "translation",
            "id": "libretranslate",
            "label": "LibreTranslate",
            "where": "server",
            "active": bool(translator) or configured_tr > 0,
            "detail": (
                "Default translator for readers without their own. "
                + (f"Using {translator['api_url']}." if translator else (
                    "Using a provider added below." if configured_tr else
                    "Not configured: set LIBRETRANSLATE_URL (and key if it needs one) in the Secret Vault, or add a provider below."
                ))
            ),
            "overridden_by_reader": True,
        },
    ] + ([{
        "service": "ocr",
        "id": "custom_defaults",
        "label": "Providers added below",
        "where": "server",
        "active": True,
        "detail": f"{configured_ocr} OCR provider(s) take priority over the built-in engine.",
        "overridden_by_reader": True,
    }] if configured_ocr else [])


@router.get("/admin/api-registry")
def get_api_registry(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import provider_management_service as pms

    _, decrypt = _vault_fns(request)
    registry: Dict[str, List[Dict[str, Any]]] = {c: [] for c in REGISTRY_CATEGORIES}
    for record in pms.list_providers(db):
        if record.service in registry:
            registry[record.service].append(_registry_entry(record, decrypt))
    return {**registry, "site_defaults": site_default_engines(db)}


class RegistryProviderPayload(BaseModel):
    category: str
    provider: Dict[str, Any]


@router.post("/admin/api-registry/provider")
def save_api_provider(
    request: Request,
    payload: RegistryProviderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import provider_management_service as pms

    category = payload.category.strip().lower()
    if category not in REGISTRY_CATEGORIES:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Unknown provider category.", field="category")
    data = payload.provider
    label = strip_all_html(str(data.get("label") or "")).strip()[:120]
    slug = strip_all_html(str(data.get("id") or label)).strip().lower()[:64]
    slug = "".join(ch if ch.isalnum() else "_" for ch in slug).strip("_") or "custom"
    if not label:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Provider name is required.", field="label")
    url = str(data.get("defaultUrl") or "").strip() or None
    if url and not url.startswith("https://"):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Provider URLs must use https://.", field="defaultUrl")
    api_key = str(data.get("apiKey") or "").strip()
    config = {
        "model": strip_all_html(str(data.get("defaultModel") or "")).strip()[:120],
        "description": strip_all_html(str(data.get("description") or "")).strip()[:500],
    }
    encrypt, decrypt = _vault_fns(request)

    record = _find_provider(db, category, slug)
    try:
        if record is None:
            record = pms.create_provider(
                db,
                provider_name=label,
                service=category,
                provider_id=slug,
                api_url=url,
                api_key=api_key if api_key and not _is_masked(api_key) else None,
                config=config,
                created_by_user_id=current_user.id,
                encrypt=encrypt,
            )
        else:
            updates: Dict[str, Any] = {"provider_name": label, "api_url": url, "config": config}
            if api_key and not _is_masked(api_key):
                updates["api_key"] = api_key
            record = pms.update_provider(db, record.id, updates, encrypt=encrypt)
    except pms.ProviderManagementError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc))

    message = f"{label} saved."
    if data.get("enabled") is False:
        pms.update_provider(db, record.id, {"status": "disabled"}, encrypt=encrypt)
    elif record.api_key or record.api_url:
        result = pms.verify_provider(db, record.id, decrypt=decrypt)
        message = (
            f"{label} saved and verified — it is now in rotation."
            if result.get("ok")
            else f"{label} saved, but its live test failed: {result.get('error')}. It stays inactive."
        )
    db.refresh(record)
    log_admin_action(db, request, current_user, "PROVIDER_SAVE", "provider", str(record.id), "success")
    return {"success": True, "message": message, "provider": _registry_entry(record, decrypt)}


@router.delete("/admin/api-registry/provider/{category}/{provider_id}")
def delete_api_provider(
    request: Request,
    category: str,
    provider_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import provider_management_service as pms

    record = _find_provider(db, category.strip().lower(), provider_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    pms.delete_provider(db, record.id)
    log_admin_action(db, request, current_user, "PROVIDER_DELETE", "provider", str(record.id), "success")
    return {"success": True}


class ConnectionTestPayload(BaseModel):
    providerId: str = Field(..., max_length=120)
    category: str = Field(..., max_length=32)


@router.post("/admin/api-registry/test-connection")
def test_api_provider(
    request: Request,
    payload: ConnectionTestPayload,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import provider_management_service as pms

    record = _find_provider(db, payload.category.strip().lower(), payload.providerId)
    if record is None:
        return {"success": False, "message": "Save this provider before testing it."}
    _, decrypt = _vault_fns(request)
    started = time.monotonic()
    result = pms.verify_provider(db, record.id, decrypt=decrypt)
    latency = int((time.monotonic() - started) * 1000)
    if result.get("ok"):
        return {"success": True, "latencyMs": latency, "message": f"Connection OK ({latency}ms). Provider is active."}
    return {"success": False, "latencyMs": latency, "message": f"Connection failed: {result.get('error') or 'no response'}"}


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------

AUDIT_RANGES = {"1d": 1, "7d": 7, "1m": 30, "1y": 365, "5y": 365 * 5}
ACTIVE_WINDOW = timedelta(minutes=15)


@router.get("/admin/audit-report")
def audit_report(
    range_key: str = Query("1d", alias="range"),
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    days = AUDIT_RANGES.get(range_key, 1)
    now = datetime.utcnow()
    cycle_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cycle_end = cycle_start + timedelta(days=1)
    since_active = now - ACTIVE_WINDOW
    since_day = now.date() - timedelta(days=days - 1)

    concurrent = (
        db.query(func.count(distinct(ReadHistory.user_id)))
        .filter(ReadHistory.last_read_at >= since_active)
        .scalar()
        or 0
    )
    watchers = dict(
        db.query(ReadHistory.manga_id, func.count(distinct(ReadHistory.user_id)))
        .filter(ReadHistory.last_read_at >= since_active)
        .group_by(ReadHistory.manga_id)
        .all()
    )
    period_views = dict(
        db.query(MangaDailyView.manga_id, func.sum(MangaDailyView.views))
        .filter(MangaDailyView.day >= since_day)
        .group_by(MangaDailyView.manga_id)
        .all()
    )
    ranked_ids = sorted(
        set(watchers) | set(period_views),
        key=lambda mid: (watchers.get(mid, 0), period_views.get(mid, 0)),
        reverse=True,
    )[:50]
    manga_rows = {m.id: m for m in db.query(Manga).filter(Manga.id.in_(ranked_ids or [0]))}
    breakdown = []
    for manga_id in ranked_ids:
        manga = manga_rows.get(manga_id)
        if manga is None:
            continue
        count = int(watchers.get(manga_id, 0))
        breakdown.append(
            {
                "id": manga.id,
                "title": manga.title,
                "cover": manga.cover_image,
                "genres": manga.genres or [],
                "current_watchers": count,
                "period_views": int(period_views.get(manga_id, 0) or 0),
                "share_percent": round(count / concurrent * 100, 1) if concurrent else 0.0,
            }
        )

    fmt = "%Y-%m-%d %H:%M:%S UTC"
    return {
        "timer": {
            "cycle_name": "UTC 24-Hour Operational Audit Cycle",
            "timezone": "Coordinated Universal Time (UTC, UTC+0)",
            "current_utc_time": now.strftime(fmt),
            "cycle_start_utc": cycle_start.strftime(fmt),
            "cycle_end_utc": cycle_end.strftime(fmt),
            "seconds_remaining": int((cycle_end - now).total_seconds()),
            "elapsed_hours": round((now - cycle_start).total_seconds() / 3600, 2),
            "progress_percent": min(100, round((now - cycle_start).total_seconds() / 864)),
        },
        "metrics": {
            "concurrent_users": int(concurrent),
            "uptime_hours": round((time.time() - PROCESS_STARTED_AT) / 3600, 2),
            "uptime_percentage": "100%",
            "registered_accounts": int(db.query(func.count(User.id)).scalar() or 0),
            "selected_range": range_key,
            "manga_monitored_count": int(db.query(func.count(Manga.id)).scalar() or 0),
            "audit_generated_at": now.isoformat(),
        },
        "manga_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@router.post("/health/diagnostics")
async def run_diagnostics(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    tests: List[Dict[str, Any]] = []

    def record(test_id: str, name: str, fn) -> None:
        started = time.monotonic()
        try:
            ok, details = fn()
        except Exception as exc:  # a failing probe is a result, not an error
            ok, details = False, f"{type(exc).__name__}: {str(exc)[:200]}"
        tests.append(
            {
                "id": test_id,
                "name": name,
                "passed": bool(ok),
                "status": "pass" if ok else "fail",
                "latency_ms": int((time.monotonic() - started) * 1000),
                "details": details,
            }
        )

    def database_probe():
        db.execute(text("SELECT 1"))
        return True, f"Database reachable; {db.query(func.count(Manga.id)).scalar() or 0} series stored."

    record("database", "Database connectivity", database_probe)

    redis_client = getattr(request.app.state, "redis", None)
    redis_started = time.monotonic()
    try:
        redis_ok = bool(redis_client is not None and await redis_client.ping())
        redis_details = "Redis cache and rate limiter reachable." if redis_ok else "Redis is not configured."
    except Exception as exc:
        redis_ok, redis_details = False, f"Redis error: {str(exc)[:200]}"
    tests.append(
        {
            "id": "redis",
            "name": "Cache & rate limiter (Redis)",
            "passed": redis_ok,
            "status": "pass" if redis_ok else "fail",
            "latency_ms": int((time.monotonic() - redis_started) * 1000),
            "details": redis_details,
        }
    )

    def worker_probe():
        from ...core.celery_app import celery_app

        replies = celery_app.control.ping(timeout=1.5) or []
        if replies:
            return True, f"{len(replies)} background worker(s) online (scraping, notifications)."
        return False, "No Celery worker answered — scraping and notifications will not run."

    record("workers", "Background workers (Celery)", worker_probe)

    def providers_probe():
        from ...models.provider_management import SystemProviderInstance

        active = (
            db.query(SystemProviderInstance.service, func.count(SystemProviderInstance.id))
            .filter(SystemProviderInstance.status == "active")
            .group_by(SystemProviderInstance.service)
            .all()
        )
        summary = ", ".join(f"{svc}: {count}" for svc, count in active) or "none active"
        return bool(active), f"Active OCR/translation/AI providers — {summary}."

    record("providers", "OCR / translation providers", providers_probe)

    def scraper_probe():
        from ...models import ApprovedSourceDomain

        domains = db.query(ApprovedSourceDomain).all()
        active = [d for d in domains if d.status == "active"]
        return bool(active), f"{len(active)} of {len(domains)} approved source websites active."

    record("scraper", "Scraper sources", scraper_probe)

    passed = sum(1 for t in tests if t["passed"])
    return {
        "overall_score": f"{passed}/{len(tests)}",
        "passed": passed,
        "total": len(tests),
        "tests": tests,
        "generated_at": datetime.utcnow().isoformat(),
    }


def health_extras(db: Session) -> Dict[str, Any]:
    """Extra sections for GET /health rendered by the admin Health page."""

    memory = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    tables = []
    for model, label in (
        (Manga, "manga"),
        (Chapter, "chapters"),
        (User, "users"),
        (ChapterReport, "chapter_reports"),
    ):
        started = time.monotonic()
        count = db.query(func.count(model.id)).scalar() or 0
        tables.append(
            {
                "table": label,
                "rows": int(count),
                "status": "healthy",
                "latency": f"{int((time.monotonic() - started) * 1000)}ms",
            }
        )
    counts = {t["table"]: t["rows"] for t in tables}

    # Manga.views is the lifetime counter bumped on every chapter read.
    total_views = int(db.query(func.coalesce(func.sum(Manga.views), 0)).scalar() or 0)

    # "Active" = distinct signed-in readers who opened a chapter in the last
    # 15 minutes; there is no server-side session table to count instead.
    active_since = datetime.utcnow() - timedelta(minutes=15)
    active_readers = int(
        db.query(func.count(distinct(ReadHistory.user_id)))
        .filter(ReadHistory.last_read_at >= active_since)
        .scalar()
        or 0
    )

    avg_score, ratings_cast = db.query(
        func.avg(MangaRating.score), func.count(MangaRating.id)
    ).one()

    uptime_seconds = int(time.time() - PROCESS_STARTED_AT)
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    uptime = f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"

    return {
        "uptime": uptime,
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.0),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_heap_used_mb": round(memory, 1),
            "memory_heap_used": f"{round(memory)} MB",
            "uptime_hours": round(uptime_seconds / 3600, 2),
            "cache_status": "Active (Healthy)",
        },
        "database": {
            "tables_health": tables,
            "manga_count": counts.get("manga", 0),
            "chapters_count": counts.get("chapters", 0),
            "cumulative_views": total_views,
            "cumulative_views_formatted": format_count(total_views),
        },
        "users": {
            "total_registered": counts.get("users", 0),
            "active_sessions_count": active_readers,
        },
        "ratings": {
            "global_avg_rating": round(float(avg_score), 1) if avg_score is not None else None,
            "total_ratings_cast": int(ratings_cast or 0),
        },
    }


# ---------------------------------------------------------------------------
# Scrape schedules
# ---------------------------------------------------------------------------


class SchedulePayload(BaseModel):
    scrape_frequency: Optional[str] = Field(None, max_length=32)
    scrape_interval_value: Optional[int] = Field(None, ge=1, le=720)
    scrape_interval_unit: Optional[str] = Field(None, max_length=8)
    auto_scrape_enabled: Optional[bool] = None
    source_url: Optional[str] = Field(None, max_length=1000)


def _interval_hours(value: Optional[int], unit: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    hours = value * (24 if (unit or "days") == "days" else 1)
    from ...services.scheduled_checks_service import MAX_INTERVAL_HOURS, MIN_INTERVAL_HOURS

    return max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, hours))


def apply_schedule(
    db: Session,
    manga: Manga,
    payload: SchedulePayload,
    actor: Optional[User] = None,
) -> Optional[int]:
    """Apply timer / pause / source-URL changes to ``manga``.

    Returns the id of a follow-up ingestion job to enqueue *after commit* when
    the source moved to a new website address: that job re-reads the chapter
    list from the new address and re-points the existing chapters at it (by
    chapter number) instead of duplicating them.
    """

    from ...services.scheduled_checks_service import schedule_next_check

    hours = _interval_hours(payload.scrape_interval_value, payload.scrape_interval_unit)
    if hours is not None:
        manga.check_interval_hours = hours
    if payload.auto_scrape_enabled is not None:
        manga.auto_scrape_enabled = payload.auto_scrape_enabled

    follow_up: Optional[int] = None
    if payload.source_url:
        from ...models import ScrapingJob
        from ...services.permissions_service import has_permission
        from ...services.series_import import ensure_website_approved
        from .admin import _parse_series_url

        url = _parse_series_url(payload.source_url)
        if url != manga.source_url:
            clash = db.query(Manga.id).filter(Manga.source_url == url, Manga.id != manga.id).first()
            if clash:
                raise ApiError(
                    ErrorCode.DUPLICATE_MANGA_URL,
                    "Another series already uses that source URL.",
                    field="source_url",
                )
            ensure_website_approved(
                db,
                actor,
                url,
                can_approve=bool(actor and has_permission(db, actor, "approve_website")),
            )
            manga.source_url = url
            job = ScrapingJob(
                manga_id=manga.id,
                source_url=url,
                status="queued",
                requested_by=actor.id if actor else None,
                options={"remap_chapters": True, "ensure_parser": True},
            )
            db.add(job)
            db.flush()
            follow_up = job.id

    if manga.auto_scrape_enabled is False:
        manga.next_check_at = None
    else:
        schedule_next_check(db, manga)
    return follow_up


@router.post("/admin/series/{manga_id}/schedule")
async def update_series_schedule(
    request: Request,
    manga_id: int,
    payload: SchedulePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series not found")
    job_id = apply_schedule(db, manga, payload, current_user)
    db.commit()
    db.refresh(manga)
    if job_id is not None:
        from ...tasks.scraper_tasks import process_manga_scrape

        process_manga_scrape.delay(job_id)
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None), manga_id)
    log_admin_action(db, request, current_user, "SERIES_SCHEDULE", "series", str(manga_id), "success")
    data = manga.to_dict()
    return {
        "success": True,
        "manga": data,
        "message": (
            f"Scrape timer updated: every {data.get('scrape_interval_value')} "
            f"{data.get('scrape_interval_unit')}. Next check {data.get('next_scrape_at') or 'paused'}."
        ),
    }


class BatchSchedulePayload(SchedulePayload):
    manga_ids: List[int] = Field(default_factory=list, max_length=500)


@router.post("/admin/series/batch-schedule")
async def batch_series_schedule(
    request: Request,
    payload: BatchSchedulePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    updated = 0
    per_series = SchedulePayload(**payload.model_dump(exclude={"manga_ids", "source_url"}))
    for manga in db.query(Manga).filter(Manga.id.in_(payload.manga_ids or [0])):
        apply_schedule(db, manga, per_series, current_user)
        updated += 1
    db.commit()
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None))
    log_admin_action(db, request, current_user, "SERIES_SCHEDULE_BATCH", "series", ",".join(map(str, payload.manga_ids[:50])), "success")
    return {"success": True, "updated": updated}


@router.delete("/admin/chapters/{chapter_id}/pages/{page_index}")
async def delete_chapter_page(
    request: Request,
    chapter_id: int,
    page_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
    pages = list(chapter.pages or [])
    if page_index < 0 or page_index >= len(pages):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    removed = pages.pop(page_index)
    chapter.pages = pages
    # The stored list is now the truth; a later re-mirror must not bring the
    # deleted page back from the source list.
    chapter.source_pages = None
    db.commit()
    from ...services import page_image_service

    page_image_service.delete_page_file(str(removed))
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None), chapter.manga_id)
    log_admin_action(
        db, request, current_user, "CHAPTER_PAGE_DELETE", "chapter", str(chapter_id), "success",
        previous_value=str(removed)[:500],
    )
    return {"success": True, "pages": len(pages)}


class LayoutPayload(BaseModel):
    split_spreads: Optional[bool] = None
    spread_mode: Optional[str] = Field(default=None, max_length=8)
    reading_direction: Optional[str] = Field(default=None, max_length=3)
    # "" / "auto" clears it back to auto-detect.
    text_language: Optional[str] = Field(default=None, max_length=5)


@router.post("/admin/series/{series_id}/layout")
async def update_series_layout(
    request: Request,
    series_id: int,
    payload: LayoutPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    """Change how a series' book-format scans are split (``spread_mode``) and
    which half reads first (``reading_direction``), then rebuild its stored
    pictures from the kept source URLs. Chapter grouping is fixed at import."""

    from ...services.chapter_grouping import normalize_layout
    from ...tasks.scraper_tasks import mirror_series_pages

    manga = db.get(Manga, series_id)
    if manga is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series not found")
    from ...services.series_import import normalize_text_language

    if payload.text_language is not None:
        manga.language = normalize_text_language(payload.text_language)

    changes = {}
    if payload.split_spreads is not None:
        changes["split_spreads"] = payload.split_spreads
    if payload.spread_mode:
        changes["spread_mode"] = payload.spread_mode
    if payload.reading_direction:
        changes["reading_direction"] = payload.reading_direction
    previous = normalize_layout(manga.scrape_layout)
    merged = {**previous, **normalize_layout(changes)}
    manga.scrape_layout = merged or None
    rebuilt = 0
    # Only re-split the pictures when the split itself changed; a text
    # language change alone needs no image work.
    if merged != previous:
        for chapter in db.query(Chapter).filter(Chapter.manga_id == manga.id).all():
            if chapter.source_pages:
                chapter.pages = list(chapter.source_pages)
                chapter.source_pages = None
                chapter.pages_bytes = None
                rebuilt += 1
    db.commit()
    if rebuilt:
        mirror_series_pages.delay(manga.id)
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None), manga.id)
    return {
        "success": True,
        "layout": merged,
        "text_language": manga.language,
        "chapters_rebuilding": rebuilt,
        "message": (
            f"Layout saved; re-compressing {rebuilt} chapters in the background."
            if rebuilt
            else "Saved."
        ),
    }


@router.post("/admin/series/{series_id}/mirror-images")
async def mirror_series_images(
    series_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    """Compress and self-host the pictures of a series that still point at the
    source site (existing series, or after a failed first attempt)."""

    from ...services import page_mirror_service
    from ...tasks.scraper_tasks import mirror_chapter_pages

    if db.get(Manga, series_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series not found")
    chapter_ids = page_mirror_service.chapters_needing_mirror(db, series_id)
    for chapter_id in chapter_ids:
        mirror_chapter_pages.delay(chapter_id)
    return {
        "success": True,
        "queued": len(chapter_ids),
        "message": (
            f"Compressing {len(chapter_ids)} chapters in the background."
            if chapter_ids
            else "Every chapter of this series is already stored on this site."
        ),
    }


@router.get("/admin/sources/health")
async def source_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    """Latest daily parser health result for every source website."""

    from ...services import source_health_service

    return {"sources": source_health_service.all_statuses(db)}


@router.get("/admin/storage")
async def storage_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("edit_series")),
) -> Dict[str, Any]:
    """How much the stored chapter pictures take and how full the volume is."""

    from ...services import storage_report_service

    return storage_report_service.build_report(db)


@router.post("/admin/maintenance/mirror-all-images")
async def mirror_all_images(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import page_mirror_service
    from ...tasks.scraper_tasks import mirror_chapter_pages

    queued = 0
    for (series_id,) in db.query(Manga.id).all():
        for chapter_id in page_mirror_service.chapters_needing_mirror(db, series_id):
            mirror_chapter_pages.delay(chapter_id)
            queued += 1
    return {"success": True, "queued": queued, "message": f"Compressing {queued} chapters in the background."}


__all__ = ["router", "site_settings_payload", "health_extras", "apply_schedule", "SchedulePayload"]
