"""Branding and footer configuration endpoints."""

from __future__ import annotations

import json
import structlog
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi import status
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy.orm import Session

from ...utils.sanitizer import strip_all_html

from ...core.db import get_db
from ...dependencies.auth import require_admin_user
from ...models import FooterSettings, Setting, User
from ...schemas.branding import BrandingUpdateRequest, FooterUpdateRequest
from ...utils.cdn import build_cdn_url
from ...utils.file_validation import validate_image_mimetype
from ...utils.image_safety import (
    ImageTooLargeError,
    InvalidImageError,
    open_image_safely,
)
from ...utils.malware_scanner import scan_file_for_malware

logger = structlog.get_logger("backend_fastapi.routers.branding")

router = APIRouter(tags=["branding"])

_BRANDING_SETTING_KEY = "branding"
_DEFAULT_BRANDING: Dict[str, Any] = {
    "logo": "",
    "logo_url": "",
    "socialLinks": {},
    "name": "",
    "tagline": "",
}

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_BRANDING_PUBLIC_PREFIX = "/branding/assets/"
_BRANDING_CLEANUP_PREFIX = "branding:"

# SRS 1H.6 abuse prevention: reject decoded-pixel-count bombs (a tiny file
# that decodes to a huge bitmap), not just oversized byte payloads.
_LOGO_MAX_PIXELS = 8000 * 8000
_DEFAULT_MAX_LOGO_BYTES = 3 * 1024 * 1024
_SVG_DOCTYPE_RE = re.compile(rb"<\s*svg[^>]*>", re.IGNORECASE)


def _load_branding(db: Session) -> Dict[str, Any]:
    record = db.query(Setting).filter(Setting.key == _BRANDING_SETTING_KEY).first()
    if not record or not record.value:
        return dict(_DEFAULT_BRANDING)
    try:
        payload = json.loads(record.value)
    except json.JSONDecodeError:
        logger.warning("Branding setting contains invalid JSON; resetting to default")
        return dict(_DEFAULT_BRANDING)

    logo = payload.get("logo") if isinstance(payload, dict) else ""
    social_links = payload.get("socialLinks") if isinstance(payload, dict) else {}
    if not isinstance(logo, str):
        logo = ""
    if isinstance(social_links, dict):
        sanitized = {k: v for k, v in social_links.items() if isinstance(v, str)}
    elif isinstance(social_links, list):
        sanitized = {
            entry.get("label", f"link-{idx}"): entry.get("url", "")
            for idx, entry in enumerate(social_links)
            if isinstance(entry, dict)
        }
    else:
        sanitized = {}
    name = payload.get("name") if isinstance(payload.get("name"), str) else ""
    tagline = payload.get("tagline") if isinstance(payload.get("tagline"), str) else ""
    return {
        "logo": logo,
        "logo_url": logo,
        "socialLinks": sanitized,
        "name": name,
        "tagline": tagline,
    }


def _clean_logo(value: Any) -> str:
    """A logo is an https URL, a same-site path, or a short emoji/text mark."""

    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith(("https://", "http://", "/")):
        return value[:500] if not value.startswith("//") else ""
    if ":" in value or len(value) > 8:
        return ""
    return strip_all_html(value)


def _store_branding(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    branding = _load_branding(db)

    logo = payload.get("logo_url") if payload.get("logo_url") is not None else payload.get("logo")
    social_links = payload.get("socialLinks")

    if logo is not None:
        branding["logo"] = _clean_logo(logo)
    branding.pop("logo_url", None)
    for key, limit in (("name", 60), ("tagline", 160)):
        value = payload.get(key)
        if isinstance(value, str):
            branding[key] = strip_all_html(value).strip()[:limit]

    if social_links is not None:
        sanitized: Dict[str, str] = {}
        if isinstance(social_links, dict):
            for key, value in social_links.items():
                if isinstance(key, str) and isinstance(value, str):
                    sanitized[key] = value
        elif isinstance(social_links, list):
            for entry in social_links:
                if not isinstance(entry, dict):
                    continue
                label = entry.get("label") or entry.get("name")
                url = entry.get("url")
                if isinstance(label, str) and isinstance(url, str):
                    sanitized[label] = url
        branding["socialLinks"] = sanitized

    record = db.query(Setting).filter(Setting.key == _BRANDING_SETTING_KEY).first()
    if not record:
        record = Setting(key=_BRANDING_SETTING_KEY, value=json.dumps(branding))
        db.add(record)
    else:
        record.value = json.dumps(branding)
    db.commit()
    return _load_branding(db)


def _branding_settings_dir(settings: Any | None) -> str | None:
    if settings is None:
        return None
    for attribute in (
        "branding_upload_dir",
        "branding_asset_dir",
        "branding_upload_path",
    ):
        value = getattr(settings, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _branding_upload_dir(request: Request) -> Path:
    settings_dir = _branding_settings_dir(getattr(request.app.state, "settings", None))
    env_dir = None
    for env_name in ("BRANDING_UPLOAD_DIR", "BRANDING_ASSET_DIR"):
        candidate = os.getenv(env_name)
        if candidate:
            env_dir = candidate
            break

    base: Path
    if settings_dir:
        base = Path(settings_dir)
    elif env_dir:
        base = Path(env_dir)
    else:
        base = Path(__file__).resolve().parents[3] / "branding_uploads"

    base.mkdir(parents=True, exist_ok=True)
    return base


def _sanitize_filename(value: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("_", value.strip())
    return cleaned or uuid.uuid4().hex


def _max_logo_bytes(request: Request) -> int:
    settings = getattr(request.app.state, "settings", None)
    configured = getattr(settings, "branding_logo_max_bytes", None)
    if isinstance(configured, int) and configured > 0:
        return configured
    env_value = os.getenv("BRANDING_LOGO_MAX_BYTES")
    if env_value and env_value.isdigit():
        return int(env_value)
    return _DEFAULT_MAX_LOGO_BYTES


async def _load_logo_bytes(upload: UploadFile, limit: int) -> bytes:
    await upload.seek(0)
    payload = await upload.read(limit + 1)
    if len(payload) > limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="logo_too_large"
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="empty_logo"
        )
    return payload


def _resolve_extension(upload: UploadFile, detected_format: str | None) -> str:
    filename_ext = Path(upload.filename or "").suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".bmp", ".svg"}
    if filename_ext in allowed:
        if filename_ext == ".jpeg":
            return ".jpg"
        return filename_ext
    if detected_format:
        format_ext = f".{detected_format.lower()}"
        if format_ext in allowed:
            return ".jpg" if format_ext == ".jpeg" else format_ext
    content_type = (upload.content_type or "").lower()
    if content_type.endswith("svg+xml"):
        return ".svg"
    if content_type.startswith("image/"):
        subtype = content_type.split("/", 1)[1]
        mapped = f".{subtype.lower()}"
        if mapped in allowed:
            return ".jpg" if mapped == ".jpeg" else mapped
    return ".png"


def _validate_svg(payload: bytes) -> None:
    if not _SVG_DOCTYPE_RE.search(payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_svg"
        )


def _validate_logo(upload: UploadFile, payload: bytes) -> tuple[str, str | None]:
    # SVG gets validated separately, for other images check mimetype and scan for malware
    content_type = (upload.content_type or "").lower()

    if scan_file_for_malware(payload):
        logger.error(
            "Malware detected in branding logo upload.",
            extra={"filename": upload.filename},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="malware_detected"
        )

    if (
        content_type
        and not content_type.startswith("image/")
        and "svg" not in content_type
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_logo_type"
        )

    if not ("svg" in content_type or str(upload.filename).endswith(".svg")):
        try:
            validate_image_mimetype(upload)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_logo_type"
            )

    image: Image.Image | None = None

    if content_type.endswith("svg+xml") or (upload.filename or "").lower().endswith(
        ".svg"
    ):
        _validate_svg(payload)
        extension = ".svg"
        return extension, "svg"

    try:
        image = open_image_safely(payload, max_pixels=_LOGO_MAX_PIXELS)
        image_format = image.format
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="logo_dimensions_too_large"
        ) from exc
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_logo"
        ) from exc
    finally:
        if image:
            image.close()

    normalized_format = image_format.lower() if image_format else None
    extension = _resolve_extension(upload, normalized_format)
    return extension, normalized_format


def _generate_logo_filename(upload: UploadFile, extension: str) -> str:
    base = Path(upload.filename or "logo").stem
    safe_base = _sanitize_filename(base) or "logo"
    return f"{safe_base}-{uuid.uuid4().hex}{extension}"


def _public_logo_path(filename: str) -> str:
    return f"{_BRANDING_PUBLIC_PREFIX}{filename}"


def _cleanup_tokens_from_form(raw: str | None) -> List[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cleanup"
        ) from exc

    tokens: List[str] = []
    candidates: Iterable[str]
    if isinstance(decoded, str):
        candidates = [decoded]
    elif isinstance(decoded, list):
        candidates = [item for item in decoded if isinstance(item, str)]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cleanup"
        )

    for token in candidates:
        token = token.strip()
        if token:
            tokens.append(token)
    return tokens


def _resolve_cleanup_path(directory: Path, token: str) -> Path | None:
    if not token.startswith(_BRANDING_CLEANUP_PREFIX):
        return None
    filename = token[len(_BRANDING_CLEANUP_PREFIX) :]
    safe = _sanitize_filename(filename)
    if safe != filename:
        return None
    target = directory / safe
    try:
        target.resolve().relative_to(directory.resolve())
    except ValueError:
        return None
    return target


def _apply_cleanup(directory: Path, tokens: List[str]) -> List[str]:
    remaining: List[str] = []
    for token in tokens:
        path = _resolve_cleanup_path(directory, token)
        if not path:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Failed to remove branding asset at %s", path, exc_info=True)
            remaining.append(token)
    return remaining


@router.get("/branding")
def get_branding(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return branding information (logo + social links)."""

    return _load_branding(db)


@router.put("/branding")
@router.post("/branding")
def update_branding(
    payload: BrandingUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    """Update branding metadata (logo URL and social links)."""

    branding = _store_branding(db, payload.model_dump(exclude_unset=True))
    return {"branding": branding}


@router.post("/branding/logo")
async def upload_branding_logo(
    request: Request,
    file: UploadFile = File(...),
    cleanup: str | None = Form(None),
    _: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    """Validate and store a branding logo asset for admin use."""

    if not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_logo")

    directory = _branding_upload_dir(request)
    try:
        payload = await _load_logo_bytes(file, _max_logo_bytes(request))
        extension, detected_format = _validate_logo(file, payload)
        filename = _generate_logo_filename(file, extension)
        target = directory / filename

        try:
            with target.open("wb") as fh:
                fh.write(payload)
        except OSError as exc:
            logger.exception("Failed to persist branding logo at %s", target)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="logo_storage_failed",
            ) from exc
    finally:
        await file.close()

    cleanup_tokens = _cleanup_tokens_from_form(cleanup)
    remaining = _apply_cleanup(directory, cleanup_tokens)
    token = f"{_BRANDING_CLEANUP_PREFIX}{filename}"
    remaining.append(token)

    public_path = _public_logo_path(filename)
    public_url = build_cdn_url(public_path)

    return {
        "logo": public_url,
        "logoUrl": public_url,
        "cleanup": remaining,
        "cleanupTokens": remaining,
        "publicPath": public_path,
        "format": detected_format,
    }


@router.get("/branding/assets/{filename}")
def serve_branding_asset(request: Request, filename: str) -> FileResponse:
    """Serve stored branding assets from disk."""

    if not filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    safe = _sanitize_filename(filename)
    if safe != filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    directory = _branding_upload_dir(request)
    target = directory / safe
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    return FileResponse(
        target, headers={"Content-Disposition": f'attachment; filename="{safe}"'}
    )


def _footer_to_dict(settings: FooterSettings | None) -> Dict[str, Any]:
    if not settings:
        return {"contact": "", "terms": "", "privacy": "", "socials": []}
    socials: List[Dict[str, Any]]
    if isinstance(settings.socials, list):
        socials = [item for item in settings.socials if isinstance(item, dict)]
    else:
        socials = []
    return {
        "contact": settings.contact or "",
        "terms": settings.terms or "",
        "privacy": settings.privacy or "",
        "socials": socials,
    }


@router.get("/footer")
def get_footer(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return footer content, social links and the public brand identity."""

    from ...services import site_content_service as content

    settings = db.query(FooterSettings).first()
    payload = _footer_to_dict(settings)
    branding = _load_branding(db)
    payload.update(content.get_footer_text(db))
    payload["social_links"] = content.get_social_links(db)
    payload["site_name"] = branding.get("name") or ""
    payload["tagline"] = branding.get("tagline") or ""
    payload["logo_url"] = branding.get("logo") or ""
    return payload


@router.put("/footer")
@router.post("/footer")
def update_footer(
    payload: FooterUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    """Update footer copy, links, and socials. Only fields present in the
    request change; omitting ``social_links`` never clears them."""

    from ...services import site_content_service as content

    settings = db.query(FooterSettings).first()
    if not settings:
        settings = FooterSettings(contact="", terms="", privacy="", socials=[])
        db.add(settings)

    data = payload.model_dump(exclude_unset=True)
    for field in ("contact", "terms", "privacy"):
        if field in data:
            setattr(settings, field, strip_all_html(data.get(field) or "")[:5000])
    content.set_footer_text(
        db, copyright=data.get("copyright"), disclaimer=data.get("disclaimer")
    )
    db.commit()

    links = data.get("social_links", data.get("socials"))
    if isinstance(links, list):
        content.replace_social_links(db, links)

    return {"message": "Footer updated", "footer": get_footer(db)}
