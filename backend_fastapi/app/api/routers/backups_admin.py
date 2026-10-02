"""Admin -> Storage & Backups (main admin only).

Connect S3-compatible storage (keys kept in the Secret Vault), choose the
weekly schedule, make a backup now, download one, upload one made elsewhere,
fetch one from the storage, and restore. Heavy work runs in the maintenance
worker (``tasks.backup_tasks``); this router only queues it and reports.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models import User
from ...services import backup_service
from ...services import secret_vault as vault
from ...services.s3_storage import S3Client, S3Target, StorageError
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/backups", tags=["backups"])

STORAGE_KEYS = (
    "BACKUP_S3_ENDPOINT",
    "BACKUP_S3_REGION",
    "BACKUP_S3_BUCKET",
    "BACKUP_S3_PREFIX",
    "BACKUP_S3_ACCESS_KEY_ID",
    "BACKUP_S3_SECRET_ACCESS_KEY",
)
MIN_PASSWORD_LENGTH = 10


def _fail(message: str, code: ErrorCode = ErrorCode.BAD_REQUEST, **details: Any) -> ApiError:
    return ApiError(code, message, details=details or None)


def _next_run(opts: Dict[str, Any]) -> Optional[str]:
    if not opts["schedule_enabled"]:
        return None
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=opts["hour_utc"], minute=0, second=0, microsecond=0)
    candidate += timedelta(days=(opts["weekday"] - now.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate.isoformat(timespec="minutes")


def _overview() -> Dict[str, Any]:
    opts = backup_service.settings()
    target = backup_service.remote_target()
    return {
        "settings": {**opts, "next_run": _next_run(opts)},
        "storage": {"connected": target is not None, **(target.public_summary() if target else {})},
        "status": backup_service.status(),
        "disk": backup_service.disk_usage(),
        "backups": backup_service.list_local(),
    }


@router.get("")
def get_backups(_: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    return _overview()


@router.get("/status")
def get_status(_: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    return {"status": backup_service.status(), "backups": backup_service.list_local()}


# -- schedule and options -------------------------------------------------


class SettingsPayload(BaseModel):
    schedule_enabled: bool
    weekday: int = Field(..., ge=0, le=6)
    hour_utc: int = Field(..., ge=0, le=23)
    keep: int = Field(..., ge=1, le=30)
    include_images: bool


@router.put("/settings")
def save_settings(
    payload: SettingsPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    values = {
        "BACKUP_SCHEDULE_ENABLED": "true" if payload.schedule_enabled else "false",
        "BACKUP_WEEKDAY": str(payload.weekday),
        "BACKUP_HOUR_UTC": str(payload.hour_utc),
        "BACKUP_KEEP": str(payload.keep),
        "BACKUP_INCLUDE_IMAGES": "true" if payload.include_images else "false",
    }
    for key, value in values.items():
        vault.store(db, key, value, actor_id=user.id)
    log_admin_action(db, request, user, "backups.settings", "backups", "settings", "success", new_value=str(values))
    return _overview()


# -- backup password --------------------------------------------------------


class PasswordPayload(BaseModel):
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=200)


@router.put("/password")
def set_password(
    payload: PasswordPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    vault.store(db, "BACKUP_PASSWORD", payload.password, actor_id=user.id)
    log_admin_action(db, request, user, "backups.password_set", "backups", "password", "success")
    return _overview()


@router.delete("/password")
def remove_password(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    vault.remove(db, "BACKUP_PASSWORD")
    log_admin_action(db, request, user, "backups.password_removed", "backups", "password", "success")
    return _overview()


# -- storage (S3-compatible) ---------------------------------------------------


class StoragePayload(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=300)
    bucket: str = Field(..., min_length=1, max_length=120)
    region: str = Field(default="auto", max_length=60)
    prefix: str = Field(default="mangaworld-backups", max_length=200)
    access_key_id: str = Field(..., min_length=1, max_length=200)
    # Left empty when only other fields change: the saved secret is kept.
    secret_access_key: Optional[str] = Field(default=None, max_length=300)


def _target_from(payload: StoragePayload) -> S3Target:
    secret = (payload.secret_access_key or "").strip() or os.getenv("BACKUP_S3_SECRET_ACCESS_KEY") or ""
    if not secret:
        raise _fail("Enter the secret access key.", field="secret_access_key")
    if not payload.endpoint.startswith(("https://", "http://")):
        raise _fail("The endpoint must start with https://", field="endpoint")
    return S3Target(
        endpoint=payload.endpoint.strip().rstrip("/"),
        bucket=payload.bucket.strip(),
        access_key_id=payload.access_key_id.strip(),
        secret_access_key=secret.strip(),
        region=(payload.region or "auto").strip() or "auto",
        prefix=(payload.prefix or "").strip().strip("/"),
    )


def _test(target: S3Target) -> None:
    try:
        with S3Client(target) as client:
            client.test()
    except StorageError as exc:
        raise _fail(f"Could not use that storage: {exc}", reason="storage_test_failed") from exc


@router.post("/storage/test")
def test_storage(payload: StoragePayload, _: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    _test(_target_from(payload))
    return {"ok": True}


@router.put("/storage")
def connect_storage(
    payload: StoragePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Test first; only a storage that accepted a write, read and delete is saved."""

    target = _target_from(payload)
    _test(target)
    values = {
        "BACKUP_S3_ENDPOINT": target.endpoint,
        "BACKUP_S3_REGION": target.region,
        "BACKUP_S3_BUCKET": target.bucket,
        "BACKUP_S3_ACCESS_KEY_ID": target.access_key_id,
        "BACKUP_S3_SECRET_ACCESS_KEY": target.secret_access_key,
    }
    for key, value in values.items():
        vault.store(db, key, value, actor_id=user.id)
    if target.prefix:
        vault.store(db, "BACKUP_S3_PREFIX", target.prefix, actor_id=user.id)
    else:
        vault.remove(db, "BACKUP_S3_PREFIX")
    log_admin_action(
        db, request, user, "backups.storage_connected", "backups", "storage", "success",
        new_value=f"{target.endpoint} / {target.bucket}",
    )
    return _overview()


@router.delete("/storage")
def disconnect_storage(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Forget the storage keys. Files already in the storage stay there."""

    for key in STORAGE_KEYS:
        vault.remove(db, key)
    log_admin_action(db, request, user, "backups.storage_disconnected", "backups", "storage", "success")
    return _overview()


@router.get("/remote")
def list_remote(_: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    try:
        return {"backups": backup_service.list_remote()}
    except (StorageError, backup_service.BackupError) as exc:
        raise _fail(str(exc), reason="storage_unavailable") from exc


class NamePayload(BaseModel):
    name: str = Field(..., min_length=5, max_length=200)


@router.post("/remote/fetch", status_code=202)
def fetch_remote(
    payload: NamePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...tasks.backup_tasks import fetch_remote as task

    _queue("fetch")
    task.delay(payload.name)
    log_admin_action(db, request, user, "backups.fetch", "backup", payload.name, "queued")
    return {"queued": True, "status": backup_service.status()}


# -- make, download, delete, upload, restore -------------------------------------


def _queue(action: str) -> None:
    try:
        backup_service.begin(action)
    except backup_service.BackupError as exc:
        raise _fail(str(exc), ErrorCode.CONFLICT, reason="job_running") from exc


class RunPayload(BaseModel):
    include_images: Optional[bool] = None


@router.post("/run", status_code=202)
def run_backup(
    payload: RunPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...tasks.backup_tasks import run_backup as task

    _queue("backup")
    task.delay("manual", payload.include_images, user.id)
    log_admin_action(db, request, user, "backups.run", "backups", "manual", "queued")
    return {"queued": True, "status": backup_service.status()}


def _path(name: str) -> Path:
    try:
        return backup_service.archive_path(name)
    except backup_service.BackupError as exc:
        raise _fail(str(exc), ErrorCode.NOT_FOUND) from exc


@router.get("/files/{name}")
def download_backup(name: str, _: User = Depends(require_main_admin_user)) -> FileResponse:
    path = _path(name)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.delete("/files/{name}")
def delete_backup(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    _path(name)
    backup_service.delete_local(name)
    log_admin_action(db, request, user, "backups.delete", "backup", name, "success")
    return _overview()


@router.post("/upload")
async def upload_backup(
    request: Request,
    filename: str = Query(..., min_length=5, max_length=200),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Raw file body (not a form), streamed to disk: archives can be many GB."""

    declared = int(request.headers.get("content-length") or 0)
    folder = backup_service.backup_dir()
    free = backup_service.disk_usage()["free"]
    if declared and declared > free - backup_service.MIN_FREE_BYTES:
        raise _fail("Not enough free disk on the server for this file.", ErrorCode.PAYLOAD_TOO_LARGE)
    fd, tmp_name = tempfile.mkstemp(dir=folder, prefix=".upload-", suffix=".part")
    tmp = Path(tmp_name)
    written = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                written += len(chunk)
                if written > free - backup_service.MIN_FREE_BYTES:
                    raise _fail("Not enough free disk on the server for this file.", ErrorCode.PAYLOAD_TOO_LARGE)
                fh.write(chunk)
        if not written:
            raise _fail("The file is empty.")
        meta = backup_service.accept_upload(tmp, filename, user.id)
    except backup_service.BackupError as exc:
        raise _fail(str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return {"backup": meta}


class RestorePayload(BaseModel):
    confirm: str
    password: Optional[str] = Field(default=None, max_length=200)


@router.post("/files/{name}/restore", status_code=202)
def restore_backup(
    name: str,
    payload: RestorePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Replace the site's database (and pictures in the backup) with this backup."""

    from ...tasks.backup_tasks import restore_backup as task

    if payload.confirm != "RESTORE":
        raise _fail('Type RESTORE to confirm: this replaces everything on the site.', field="confirm")
    _path(name)
    _queue("restore")
    token = vault.seal(payload.password) if payload.password else None
    log_admin_action(db, request, user, "backups.restore", "backup", name, "queued")
    task.delay(name, token, user.id)
    return {"queued": True, "status": backup_service.status()}


__all__ = ["router"]
