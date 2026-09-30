"""User settings endpoints for profile data and integration API keys."""

from __future__ import annotations

import io
import structlog
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from PIL import Image

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import Bookmark, ReadHistory, User, UserAPIKey
from ...schemas.user_settings import (
    UserSettingsResponse,
    UpdateUserSettingsRequest,
    UpdateUserAPIKeysResponse,
    UploadProfileImageResponse,
)
from ...schemas.processing_settings import (
    ProcessingSettingsResponse,
    UpdateProcessingSettingsRequest,
)
from ...services.provider_config import (
    ProviderConfigError,
    default_response_payload,
    normalize_provider_payload,
    record_to_response,
)
from ...services import processing_settings_service, usage_limit_service
from ...services.overlay_fonts import list_fonts
from ...services.processing_settings_service import ProcessingSettingsError
from ...utils.email_crypto import allow_email_decryption, mask_email
from ...utils.endpoint_limiter import sync_endpoint_limiter
from ...utils.file_validation import validate_image_mimetype
from ...utils.image_safety import (
    ImageTooLargeError,
    InvalidImageError,
    open_image_safely,
)
from ...utils.malware_scanner import scan_file_for_malware
from ...utils.sanitizer import strip_all_html

logger = structlog.get_logger("backend_fastapi.routers.user_settings")

router = APIRouter(prefix="/user", tags=["user_settings"])

VALID_API_PROVIDERS = {"ocr", "translation", "ai"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

PROFILE_PUBLIC_PREFIX = "/api/user/profile-image/"
PROFILE_MAX_DIMENSION = 512
PROFILE_MAX_PIXELS = 4096 * 4096

_UNSET = object()
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ProfileImageError(RuntimeError):
    """Raised when a profile image upload fails validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _settings_profile_dir(request: Request) -> Optional[str]:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return None
    return getattr(settings, "profile_upload_dir", None)


def _profile_upload_dir(request: Request) -> Path:
    base = _settings_profile_dir(request) or os.getenv("PROFILE_UPLOAD_DIR")
    if base:
        directory = Path(base)
    else:
        directory = Path(__file__).resolve().parents[3] / "profile_uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _secure_filename(value: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("_", value.strip())
    return cleaned or uuid.uuid4().hex


def _build_profile_url(filename: str) -> str:
    return f"{PROFILE_PUBLIC_PREFIX}{filename}"


def _resolve_managed_profile_path(
    request: Request, path: Optional[str]
) -> Optional[Path]:
    if not path or not isinstance(path, str):
        return None
    if not path.startswith(PROFILE_PUBLIC_PREFIX):
        return None
    filename = path[len(PROFILE_PUBLIC_PREFIX) :]
    safe = _secure_filename(filename)
    if safe != filename:
        return None
    return _profile_upload_dir(request) / safe


def _max_upload_bytes(request: Request) -> int:
    settings = getattr(request.app.state, "settings", None)
    configured = getattr(settings, "profile_image_max_bytes", None)
    if isinstance(configured, int) and configured > 0:
        return configured
    env_value = os.getenv("PROFILE_IMAGE_MAX_BYTES")
    if env_value and env_value.isdigit():
        return int(env_value)
    return 5 * 1024 * 1024


def _load_image_bytes(request: Request, upload: UploadFile) -> bytes:
    max_bytes = _max_upload_bytes(request)
    upload.file.seek(0)
    payload = upload.file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ProfileImageError(
            "too_large", "Profile image exceeds the maximum allowed size."
        )
    if not payload:
        raise ProfileImageError("empty", "Uploaded file was empty.")
    return payload


def _sanitize_profile_image(request: Request, upload: UploadFile) -> Tuple[str, bytes]:
    validate_image_mimetype(upload)
    raw = _load_image_bytes(request, upload)

    if scan_file_for_malware(raw):
        # Quarantine/alert could be handled here
        logger.error(
            "Malware detected in profile image upload.",
            extra={"filename": upload.filename},
        )
        raise ProfileImageError(
            "malware_detected", "Malware detected in upload. File quarantined."
        )

    try:
        image = open_image_safely(raw, max_pixels=PROFILE_MAX_PIXELS)
    except ImageTooLargeError as exc:
        raise ProfileImageError("too_large", "Uploaded image is too large.") from exc
    except InvalidImageError as exc:
        raise ProfileImageError(
            "invalid_image", "Uploaded file is not a valid image."
        ) from exc

    image = image.convert("RGBA")
    image.thumbnail((PROFILE_MAX_DIMENSION, PROFILE_MAX_DIMENSION), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    sanitized = buffer.getvalue()
    buffer.close()

    filename = f"{uuid.uuid4().hex}.png"
    return filename, sanitized


def _vault(request: Request):
    return getattr(request.app.state, "integration_key_vault", None)


def _serialize_api_keys(
    request: Request, records: Dict[str, UserAPIKey]
) -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    decryptor = getattr(_vault(request), "decrypt", None)
    for provider in VALID_API_PROVIDERS:
        record = records.get(provider)
        if record:
            payload[provider] = record_to_response(record, decrypt=decryptor)
        else:
            payload[provider] = default_response_payload(provider)
    return payload


def _normalize_simple_provider_value(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return {"apiKey": cleaned} if cleaned else None
    if isinstance(value, dict):
        return value
    if value is False:
        return None
    return _UNSET


def _collect_api_provider_payloads(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    updates: Dict[str, Any] = {}

    for provider in VALID_API_PROVIDERS:
        normalized = _normalize_simple_provider_value(data.get(provider))
        if normalized is _UNSET:
            continue
        if normalized is not None or provider not in updates:
            updates[provider] = normalized

    alias_map = {
        "ocrKey": "ocr",
        "ocr_api_key": "ocr",
        "translationKey": "translation",
        "translation_api_key": "translation",
        "aiKey": "ai",
        "ai_api_key": "ai",
    }

    for alias, provider in alias_map.items():
        if alias not in data:
            continue
        normalized = _normalize_simple_provider_value(data.get(alias))
        if normalized is _UNSET:
            continue
        if provider in updates and isinstance(updates[provider], dict):
            continue
        updates[provider] = normalized

    return updates


def _apply_provider_updates(
    request: Request, db: Session, user: User, payloads: Dict[str, Any]
):
    if not payloads:
        api_keys = db.query(UserAPIKey).filter_by(user_id=user.id).all()
        return {record.provider: record for record in api_keys}

    vault = _vault(request)

    for provider, raw_value in payloads.items():
        if provider not in VALID_API_PROVIDERS:
            raise ProviderConfigError(f"Unsupported provider: {provider}")

        normalized_payload = None
        if raw_value is not None:
            normalized_payload = normalize_provider_payload(provider, raw_value)

        record = (
            db.query(UserAPIKey).filter_by(user_id=user.id, provider=provider).first()
        )

        if not normalized_payload:
            if record:
                db.delete(record)
            continue

        if not record:
            record = UserAPIKey(user_id=user.id, provider=provider)
            db.add(record)

        api_key_plain = normalized_payload.get("api_key")
        if vault and api_key_plain:
            api_key_encrypted = vault.encrypt(api_key_plain)
        else:
            api_key_encrypted = api_key_plain

        record.api_key = api_key_encrypted
        record.config = normalized_payload.get("config")

    db.flush()
    db.refresh(user)

    api_keys = db.query(UserAPIKey).filter_by(user_id=user.id).all()
    return {record.provider: record for record in api_keys}


@router.get("/settings", response_model=UserSettingsResponse)
def get_user_settings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's profile settings."""

    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    api_keys = db.query(UserAPIKey).filter_by(user_id=user.id).all()
    records = {record.provider: record for record in api_keys}

    with allow_email_decryption():
        email_plain = user.email

    return {
        "email": None,
        "email_hash": getattr(user, "email_hash", None),
        "email_masked": mask_email(email_plain),
        "profile_image": user.profile_image,
        "language": user.language,
        "username": user.username,
        "name": getattr(user, "name", None),
        "api_keys": _serialize_api_keys(request, records),
    }


@router.post("/settings", response_model=UserSettingsResponse)
@router.put("/settings", response_model=UserSettingsResponse)
def update_user_settings(
    request: Request,
    payload: UpdateUserSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's profile metadata and provider configuration."""

    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    data = payload.model_dump(exclude_none=True)

    avatar_url = data.get("avatarUrl") or data.get("avatar_url")
    if avatar_url is not None and "profile_image" not in data:
        data["profile_image"] = avatar_url

    preferred_language = data.get("preferredLanguage") or data.get("preferred_language")
    if preferred_language is not None and "language" not in data:
        data["language"] = preferred_language

    if "profile_image" in data:
        incoming_image = data.get("profile_image")
        if incoming_image != user.profile_image:
            old_path = _resolve_managed_profile_path(request, user.profile_image)
            user.profile_image = incoming_image
            if old_path and old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    logger.warning("Failed to delete old profile image at %s", old_path)

    if "username" in data:
        raw_username = data.get("username")
        if raw_username is None or not isinstance(raw_username, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_username"
            )
        username = strip_all_html(raw_username.strip())
        if not username or not USERNAME_PATTERN.fullmatch(username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_username"
            )
        conflict = (
            db.query(User)
            .filter(func.lower(User.username) == username.lower(), User.id != user.id)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="username_taken"
            )
        user.username = username

    if "name" in data:
        raw_name = data.get("name")
        if raw_name is None or not isinstance(raw_name, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_name"
            )
        user.name = strip_all_html(raw_name.strip())

    if "language" in data:
        lang_value = data.get("language")
        if not isinstance(lang_value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_language"
            )
        lang = lang_value.strip()
        if not lang or len(lang) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_language"
            )
        user.language = lang

    payload_keys: Dict[str, Any] = {}
    if isinstance(data.get("api_keys"), dict):
        for provider, value in data["api_keys"].items():
            if provider not in VALID_API_PROVIDERS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_provider"
                )
            payload_keys[provider] = value

    provider_aliases = _collect_api_provider_payloads(
        data.get("apiProviders") or data.get("api_providers")
    )
    if provider_aliases:
        payload_keys.update(provider_aliases)

    top_level_aliases = _collect_api_provider_payloads(data)
    for key, value in top_level_aliases.items():
        if key not in payload_keys:
            payload_keys[key] = value

    legacy_fields = (
        ("ocr", "ocr_api"),
        ("translation", "translation_api"),
        ("ai", "ai_api"),
    )
    for provider, field in legacy_fields:
        if field in data and provider not in payload_keys:
            payload_keys[provider] = data.get(field)

    try:
        records = _apply_provider_updates(request, db, user, payload_keys)
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(user)

    with allow_email_decryption():
        email_plain = user.email

    return {
        "email": None,
        "email_hash": getattr(user, "email_hash", None),
        "email_masked": mask_email(email_plain),
        "profile_image": user.profile_image,
        "language": user.language,
        "username": user.username,
        "name": getattr(user, "name", None),
        "api_keys": _serialize_api_keys(request, records),
    }


def _processing_settings_payload(db: Session, user_id: int) -> Dict[str, Any]:
    record = processing_settings_service.get_or_create(db, user_id)
    payload = processing_settings_service.to_dict(record)
    snap = usage_limit_service.snapshot(db, user_id)
    if snap.limit_value:
        payload["usage_remaining"] = max(0, snap.limit_value - snap.usage_current)
        payload["ai_usage_remaining"] = max(0, snap.limit_value - snap.ai_usage_current)
    else:
        payload["usage_remaining"] = None
        payload["ai_usage_remaining"] = None
    payload["usage_current"] = snap.usage_current
    payload["ai_usage_current"] = snap.ai_usage_current
    payload["usage_period_start"] = snap.period_start.isoformat()
    payload["usage_reset_at"] = snap.period_end.isoformat()
    return payload


@router.get("/processing-settings", response_model=ProcessingSettingsResponse)
def get_processing_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Part 2 processing preferences: usage limits (2E), AI assistance
    (2A.3), voluntary cache sharing (2C.4.4), and overlay rendering (2F.2)."""

    return _processing_settings_payload(db, current_user.id)


@router.patch("/processing-settings", response_model=ProcessingSettingsResponse)
@router.put("/processing-settings", response_model=ProcessingSettingsResponse)
def update_processing_settings(
    payload: UpdateProcessingSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updates = payload.model_dump(exclude_none=True)
    try:
        processing_settings_service.update(db, current_user.id, updates)
    except ProcessingSettingsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return _processing_settings_payload(db, current_user.id)


@router.get("/overlay-fonts")
def get_overlay_fonts(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The curated overlay font set (2F.2A), admin-extensible without a
    code change (see SystemSettings.overlay_fonts)."""

    return {"fonts": list_fonts(db)}


@router.put("/api-keys", response_model=UpdateUserAPIKeysResponse)
def update_user_api_keys(
    request: Request,
    payload: UpdateUserSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update API keys for providers without changing other settings."""
    sync_endpoint_limiter.check_limit(
        request, f"api_keys_update:{current_user.id}", limit=20, window_seconds=3600
    )

    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    data = payload.model_dump(exclude_none=True)
    payloads: Dict[str, Any] = {}
    payloads.update(_collect_api_provider_payloads(data))
    payloads.update(
        _collect_api_provider_payloads(
            data.get("apiProviders") or data.get("api_providers")
        )
    )

    try:
        records = _apply_provider_updates(request, db, user, payloads)
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    db.commit()

    return {"success": True, "api_keys": _serialize_api_keys(request, records)}


@router.post("/profile-image", response_model=UploadProfileImageResponse)
def upload_profile_image(
    request: Request,
    file: UploadFile | None = None,
    image: UploadFile | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Handle profile image uploads for the current user."""

    upload = file or image
    if not upload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_file")

    try:
        filename, payload = _sanitize_profile_image(request, upload)
    except ProfileImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    storage_dir = _profile_upload_dir(request)
    target = storage_dir / filename

    try:
        with target.open("wb") as fh:
            fh.write(payload)
    except OSError as exc:
        logger.exception("Failed to store profile image at %s", target)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_failed"
        ) from exc

    new_url = _build_profile_url(filename)

    user = db.get(User, current_user.id)
    if not user:
        try:
            target.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    previous_path = _resolve_managed_profile_path(request, user.profile_image)
    user.profile_image = new_url
    db.commit()
    db.refresh(user)

    if previous_path and previous_path.exists():
        try:
            previous_path.unlink()
        except OSError:
            logger.warning(
                "Failed to delete previous profile image at %s", previous_path
            )

    with allow_email_decryption():
        email_plain = user.email

    return {
        "profile_image": user.profile_image,
        "email": None,
        "email_hash": getattr(user, "email_hash", None),
        "email_masked": mask_email(email_plain),
        "username": user.username,
        "name": getattr(user, "name", None),
    }


@router.get("/profile-image/{filename}")
def serve_profile_image(
    request: Request,
    filename: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Serve a stored profile image for authenticated users."""

    _ = current_user  # Ensures authentication via dependency

    if not filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    safe = _secure_filename(filename)
    if safe != filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    storage_dir = _profile_upload_dir(request)
    target = storage_dir / safe
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    return FileResponse(
        target, headers={"Content-Disposition": f'attachment; filename="{safe}"'}
    )


# --------------------------------------------------------------------------
# Data export and account deletion (SRS 1E.6.2 / 1E.6.3)
# --------------------------------------------------------------------------


@router.get("/me/export")
def export_my_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Export the caller's own data (SRS 1E.6.3).

    Credentials are NEVER included — they cannot be read back even by their
    owner (SRS 1H.3). Only that a provider is configured is disclosed.
    """

    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    with allow_email_decryption():
        account = {
            "user_id": user.id,
            "email_masked": mask_email(getattr(user, "email_plaintext", None)),
            "display_name": getattr(user, "name", None),
            "username": user.username,
            "identity_provider": user.provider,
            "email_verified": bool(getattr(user, "email_verified", False)),
            "role": user.role.value if user.role else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    history = [
        {
            "manga_id": h.manga_id,
            "chapter_id": h.chapter_id,
            "last_read_at": h.last_read_at.isoformat() if h.last_read_at else None,
        }
        for h in db.query(ReadHistory)
        .filter(ReadHistory.user_id == user.id)
        .order_by(ReadHistory.id.desc())
        .limit(10000)
        .all()
    ]
    bookmarks = [
        {"manga_id": b.manga_id, "chapter_id": b.chapter_id}
        for b in db.query(Bookmark)
        .filter(Bookmark.user_id == user.id)
        .order_by(Bookmark.id.desc())
        .limit(10000)
        .all()
    ]
    # Providers: presence only, never the credential value.
    configured_providers = sorted(
        {k.provider for k in db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id)}
    )

    return {
        "account": account,
        "reading_history": history,
        "bookmarks": bookmarks,
        "configured_providers": configured_providers,
        "note": "Credentials are intentionally excluded and cannot be exported.",
    }


@router.delete("/me")
def delete_my_account(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete the caller's account (SRS 1E.6.2).

    Credentials are deleted immediately and irrecoverably; reading history,
    bookmarks and profile assets are removed; the account is deactivated so its
    sessions stop working on the next request; audit-log entries are retained
    (they record system actions, not personal content); the user_id is not
    reused.
    """

    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    # Credentials — irrecoverable.
    db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id).delete(
        synchronize_session=False
    )
    # History + bookmarks.
    db.query(ReadHistory).filter(ReadHistory.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(Bookmark).filter(Bookmark.user_id == user.id).delete(
        synchronize_session=False
    )

    # Profile asset on managed local storage.
    old_path = _resolve_managed_profile_path(request, user.profile_image)
    if old_path and old_path.exists():
        try:
            old_path.unlink()
        except OSError:
            logger.warning("Failed to delete profile image during account deletion")

    # Deactivate + strip customization (audit log rows are left untouched).
    user.is_active = False
    user.profile_image = None
    user.username = None
    user.name = None
    db.commit()

    return {"message": "account_deleted", "user_id": user.id}
