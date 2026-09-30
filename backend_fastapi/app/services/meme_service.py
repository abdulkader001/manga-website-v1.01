"""User-uploaded memes -- Tier 2 (SRS 3B.2).

Validated by content inspection (never file extension), same as profile
uploads (1E.5.2): mimetype sniff, malware scan, then decode with Pillow.
Converted to WebP server-side so a 2 MB phone-camera JPEG typically lands
under 300 KB. Deduplicated by content hash so the same image uploaded by
many people is stored once (3B.4).
"""

from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from fastapi import Request, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import User
from ..models.community import REPORT_TARGET_MEME, ContentReport, MemeUpload
from ..utils.cdn import build_cdn_url
from ..utils.file_validation import validate_image_mimetype
from ..utils.image_safety import (
    ImageTooLargeError,
    InvalidImageError,
    open_image_safely,
)
from ..utils.malware_scanner import scan_file_for_malware
from . import moderation_service

MEME_MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB in (3B.2)
MEME_MAX_DIMENSION = 800
# Generous relative to the 800x800 output (well above any legitimate phone
# photo) while staying under Pillow's global bomb-detection ceiling (4G.3.1).
MEME_MAX_PIXELS = 6000 * 6000
MEME_PUBLIC_PREFIX = "/api/community/memes/file/"


def _upload_dir(request: Request) -> Path:
    settings = getattr(request.app.state, "settings", None)
    base = (
        getattr(settings, "meme_upload_dir", None) if settings else None
    ) or os.getenv("MEME_UPLOAD_DIR")
    directory = (
        Path(base) if base else Path(__file__).resolve().parents[2] / "meme_uploads"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_capped(upload: UploadFile) -> bytes:
    upload.file.seek(0)
    payload = upload.file.read(MEME_MAX_UPLOAD_BYTES + 1)
    if len(payload) > MEME_MAX_UPLOAD_BYTES:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Meme uploads are limited to 2 MB.",
        )
    if not payload:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Uploaded file was empty.")
    return payload


def _to_webp(raw: bytes) -> Tuple[bytes, int, int]:
    try:
        image = open_image_safely(raw, max_pixels=MEME_MAX_PIXELS)
    except ImageTooLargeError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "Uploaded image is too large."
        ) from exc
    except InvalidImageError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "Uploaded file is not a valid image."
        ) from exc

    image = image.convert("RGBA") if image.mode in ("P", "LA") else image.convert("RGB")
    image.thumbnail((MEME_MAX_DIMENSION, MEME_MAX_DIMENSION), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=80, method=6)
    webp_bytes = buffer.getvalue()
    buffer.close()
    return webp_bytes, image.width, image.height


def upload_meme(
    db: Session, request: Request, upload: UploadFile, *, user: User
) -> MemeUpload:
    moderation_service.assert_can_participate(user)
    validate_image_mimetype(upload)
    raw = _read_capped(upload)

    if scan_file_for_malware(raw):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Malware detected in upload.")

    webp_bytes, width, height = _to_webp(raw)
    content_hash = hashlib.sha256(webp_bytes).hexdigest()

    existing = (
        db.query(MemeUpload)
        .filter(
            MemeUpload.content_hash == content_hash, MemeUpload.removed_at.is_(None)
        )
        .one_or_none()
    )
    if existing is not None:
        return existing  # 3B.4 dedup: identical image already stored once.

    filename = f"{content_hash}.webp"
    (_upload_dir(request) / filename).write_bytes(webp_bytes)

    meme = MemeUpload(
        uploader_id=user.id,
        content_hash=content_hash,
        url=build_cdn_url(f"{MEME_PUBLIC_PREFIX}{filename}")
        or f"{MEME_PUBLIC_PREFIX}{filename}",
        width=width,
        height=height,
        byte_size=len(webp_bytes),
    )
    db.add(meme)
    db.commit()
    db.refresh(meme)
    return meme


def resolve_file_path(db: Session, request: Request, filename: str) -> Optional[Path]:
    safe = "".join(c for c in filename if c.isalnum() or c in ("-", "_", "."))
    if safe != filename or not safe.endswith(".webp"):
        return None
    content_hash = safe[: -len(".webp")]
    # A removed meme's row still exists (soft delete, dedup key stays
    # unique) -- gate on it so a removal is enforced even if the on-disk
    # file hasn't been cleaned up yet, or was already gone.
    meme = (
        db.query(MemeUpload)
        .filter(
            MemeUpload.content_hash == content_hash, MemeUpload.removed_at.is_(None)
        )
        .one_or_none()
    )
    if meme is None:
        return None
    path = _upload_dir(request) / safe
    return path if path.exists() else None


def remove_meme(
    db: Session, request: Request, *, meme_id: int, reason: str
) -> Optional[MemeUpload]:
    meme = db.get(MemeUpload, meme_id)
    if meme is None:
        return None
    meme.removed_at = datetime.utcnow()
    meme.removed_reason = reason
    db.commit()
    db.refresh(meme)

    filename = f"{meme.content_hash}.webp"
    try:
        (_upload_dir(request) / filename).unlink(missing_ok=True)
    except OSError:
        pass  # best-effort -- resolve_file_path's DB check is authoritative
    return meme


def report_meme(
    db: Session, *, user: User, meme_id: int, reason: Optional[str]
) -> ContentReport:
    """Image-specific reporting (3B.4), feeding the same moderator queue a
    comment report does."""

    moderation_service.assert_can_participate(user)
    meme = db.get(MemeUpload, meme_id)
    if meme is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Meme not found.")

    report = ContentReport(
        target_type=REPORT_TARGET_MEME,
        target_id=meme_id,
        reporter_id=user.id,
        reason=(reason or "").strip()[:255] or None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def meme_to_dict(meme: MemeUpload) -> dict:
    return {
        "id": meme.id,
        "url": meme.url,
        "width": meme.width,
        "height": meme.height,
        "byte_size": meme.byte_size,
    }


__all__ = [
    "MEME_MAX_UPLOAD_BYTES",
    "upload_meme",
    "resolve_file_path",
    "remove_meme",
    "meme_to_dict",
]
