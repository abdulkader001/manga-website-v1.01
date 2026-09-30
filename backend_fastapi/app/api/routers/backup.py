"""Administrative database backup and restore endpoints."""

from __future__ import annotations

import structlog
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from ...utils.python_multipart import MultipartParser, parse_options_header
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import DATABASE_URL, get_db
from ...dependencies.auth import require_main_admin_user

logger = structlog.get_logger("backend_fastapi.backup")

SQLITE_HEADER = b"SQLite format 3\x00"
# pg_dump's custom-format archive (`--format=custom`) always opens with this
# 5-byte magic (github.com/postgres/postgres src/bin/pg_dump/pg_backup_archiver.c).
POSTGRES_DUMP_HEADER = b"PGDMP"
MAX_BACKUP_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
PG_DUMP_RESTORE_TIMEOUT_SECONDS = 600

router = APIRouter(prefix="/backup", tags=["backup"])


def _extract_uploaded_backup(
    content_type: str | None, body: bytes
) -> Tuple[str | None, bytes]:
    """Return the uploaded backup payload from a multipart/form-data body."""

    if not body or not content_type:
        return None, b""

    try:
        _, params = parse_options_header(content_type)
    except Exception:  # pragma: no cover - defensive guard
        return None, b""

    boundary = params.get(b"boundary")
    if boundary is None:
        return None, b""

    boundary_str = (
        boundary.decode("latin-1") if isinstance(boundary, bytes) else boundary
    )

    result_filename: str | None = None
    result_content = bytearray()
    result_captured = False

    current_content = bytearray()
    header_name = bytearray()
    header_value = bytearray()
    capture = False

    def on_part_begin() -> None:
        nonlocal capture, current_content, header_name, header_value
        capture = False
        current_content = bytearray()
        header_name = bytearray()
        header_value = bytearray()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data[start:end])

    def on_header_end() -> None:
        nonlocal capture, result_filename, header_name, header_value
        name = header_name.decode("latin-1").lower().strip()
        value = header_value.decode("latin-1").strip()
        if name == "content-disposition":
            try:
                _, options = parse_options_header(value)
            except Exception:  # pragma: no cover - defensive guard
                capture = False
            else:
                field_name = options.get(b"name")
                if (
                    not result_captured
                    and field_name
                    and field_name.decode("latin-1") == "backup"
                ):
                    capture = True
                    filename_bytes = options.get(b"filename")
                    if filename_bytes:
                        result_filename = filename_bytes.decode("latin-1")
                else:
                    capture = False
        header_name = bytearray()
        header_value = bytearray()

    def on_headers_finished() -> None:  # pragma: no cover - required by parser API
        return None

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if capture and not result_captured:
            current_content.extend(data[start:end])

    def on_part_end() -> None:
        nonlocal result_captured, result_content, capture
        if capture and not result_captured:
            result_content = current_content.copy()
            result_captured = True
        capture = False

    def on_end() -> None:  # pragma: no cover - required by parser API
        return None

    parser = MultipartParser(
        boundary_str,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
            "on_end": on_end,
        },
    )
    parser.write(body)
    parser.finalize()

    if result_captured:
        return result_filename, bytes(result_content)

    return None, b""


def _database_url() -> str:
    # Single source of truth (P12-B-1): read the already-resolved,
    # fail-loudly-if-missing URL the app booted with, rather than a second
    # independent `os.getenv("DATABASE_URL", ...)` that could quietly drift
    # from it or fall back to something the running app never used.
    return DATABASE_URL


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql")


def _database_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.replace("sqlite:///", "", 1))
    if database_url.startswith("sqlite://"):
        return Path(database_url.replace("sqlite://", "", 1))
    return Path(database_url)


def _ensure_sqlite_path() -> Path:
    path = _database_path(_database_url())
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database file not found.",
        )
    return path


def _pg_conn_params(url: str) -> dict[str, str]:
    parsed = make_url(url)
    return {
        "host": parsed.host or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.database or "",
    }


def _require_binary(name: str) -> str:
    """Locate a Postgres client-tools binary, or fail with a clear,
    documented 501 rather than a bare crash.

    F-33: the runtime image this app ships in (``backend_fastapi/Dockerfile``)
    does not currently install the ``postgresql-client`` package. Until it
    does, Postgres backup/restore correctly reports itself as unsupported
    here instead of either crashing or silently no-op'ing.
    """

    path = shutil.which(name)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"'{name}' is not available in this deployment's runtime "
                "image. Install the postgresql-client package to enable "
                "Postgres backup/restore."
            ),
        )
    return path


def _run_pg_tool(binary: str, args: list[str], params: dict[str, str]) -> None:
    env = dict(os.environ, PGPASSWORD=params["password"])
    try:
        result = subprocess.run(
            [binary, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=PG_DUMP_RESTORE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error(f"{binary} timed out", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{binary} timed out.",
        ) from exc

    if result.returncode != 0:
        # stderr never contains PGPASSWORD (passed via env, not argv) and is
        # truncated before logging so a pathological error can't flood logs.
        logger.error(
            f"{binary} failed (exit={result.returncode})",
            stderr=result.stderr[-2000:],
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database {'backup' if binary == 'pg_dump' else 'restore'} failed.",
        )


def _create_sqlite_backup() -> FileResponse:
    """SQLite snapshot via ``sqlite3``'s own backup API (F-33): unlike a raw
    file copy, this takes the locks SQLite itself uses and correctly
    incorporates WAL-mode data not yet checkpointed into the main file, so it
    can't race a concurrent writer into an inconsistent snapshot."""

    db_path = _ensure_sqlite_path()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite")
    tmp.close()

    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(tmp.name)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    def _cleanup(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            logger.warning("Temporary backup file cleanup failed", exc_info=True)

    background = BackgroundTask(_cleanup, tmp.name)
    return FileResponse(
        tmp.name,
        filename="backup.sqlite",
        media_type="application/octet-stream",
        background=background,
    )


def _create_postgres_backup(url: str) -> FileResponse:
    """Postgres snapshot via ``pg_dump --format=custom`` (F-33), the format
    ``pg_restore`` expects back on restore."""

    pg_dump = _require_binary("pg_dump")
    params = _pg_conn_params(url)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pgdump")
    tmp.close()

    _run_pg_tool(
        pg_dump,
        [
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "-h", params["host"],
            "-p", params["port"],
            "-U", params["user"],
            "-d", params["dbname"],
            "-f", tmp.name,
        ],
        params,
    )

    def _cleanup(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            logger.warning("Temporary backup file cleanup failed", exc_info=True)

    background = BackgroundTask(_cleanup, tmp.name)
    return FileResponse(
        tmp.name,
        filename="backup.pgdump",
        media_type="application/octet-stream",
        background=background,
    )


@router.post("/create")
def create_backup(
    _: Session = Depends(get_db),
    __: None = Depends(require_main_admin_user),
) -> FileResponse:
    """Return a database snapshot for the current environment."""

    url = _database_url()
    if _is_sqlite(url):
        return _create_sqlite_backup()
    if _is_postgres(url):
        return _create_postgres_backup(url)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Backups are only supported for sqlite and postgresql databases.",
    )


def _restore_sqlite(contents: bytes, db_path: Path) -> None:
    """Restore via ``sqlite3``'s own backup API (F-33) instead of a raw
    ``shutil.copyfile`` onto the live file -- see ``_create_sqlite_backup``
    for why that matters for a database still being written to."""

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite")
    try:
        tmp_file.write(contents)
        tmp_file.flush()
    finally:
        tmp_file.close()

    try:
        source = sqlite3.connect(tmp_file.name)
        try:
            dest = sqlite3.connect(str(db_path))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    finally:
        try:
            os.remove(tmp_file.name)
        except OSError:
            logger.warning("Temporary restore file could not be removed", exc_info=True)


def _restore_postgres(contents: bytes, url: str) -> None:
    """Restore via ``pg_restore --clean`` (F-33), dropping/recreating
    existing objects before loading the dump so the result matches the
    snapshot exactly rather than merging on top of current state."""

    pg_restore = _require_binary("pg_restore")
    params = _pg_conn_params(url)

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pgdump")
    try:
        tmp_file.write(contents)
        tmp_file.flush()
    finally:
        tmp_file.close()

    try:
        _run_pg_tool(
            pg_restore,
            [
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "-h", params["host"],
                "-p", params["port"],
                "-U", params["user"],
                "-d", params["dbname"],
                tmp_file.name,
            ],
            params,
        )
    finally:
        try:
            os.remove(tmp_file.name)
        except OSError:
            logger.warning("Temporary restore file could not be removed", exc_info=True)


@router.post("/restore")
async def restore_backup(
    request: Request,
    _: Session = Depends(get_db),
    __: None = Depends(require_main_admin_user),
) -> JSONResponse:
    """Restore the database from an uploaded backup."""

    url = _database_url()
    if _is_sqlite(url):
        db_path = _ensure_sqlite_path()
        expected_header = SQLITE_HEADER
        invalid_reason = "invalid_sqlite"
        invalid_message = "Uploaded file is not a valid SQLite database."
    elif _is_postgres(url):
        db_path = None
        expected_header = POSTGRES_DUMP_HEADER
        invalid_reason = "invalid_postgres_dump"
        invalid_message = (
            "Uploaded file is not a valid pg_dump custom-format archive."
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Restore is only supported for sqlite and postgresql databases.",
        )

    filename: str | None = None
    body = await request.body()
    fallback_name, contents = _extract_uploaded_backup(
        request.headers.get("content-type"), body
    )
    if fallback_name:
        filename = fallback_name

    if not contents:
        logger.warning("Backup restore rejected: empty upload")
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Uploaded file is empty.",
            details={"reason": "empty_file"},
        )

    if len(contents) > MAX_BACKUP_UPLOAD_SIZE:
        logger.warning(
            "Backup restore rejected: uploaded file too large (size=%s bytes)",
            len(contents),
        )
        raise ApiError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            "Backup file exceeds the 100 MB size limit.",
            details={"reason": "file_too_large"},
        )

    if not contents.startswith(expected_header):
        logger.warning(
            "Backup restore rejected: invalid header from %s",
            filename or "uploaded file",
        )
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            invalid_message,
            details={"reason": invalid_reason},
        )

    if db_path is not None:
        _restore_sqlite(contents, db_path)
    else:
        _restore_postgres(contents, url)

    logger.info("Database restored from uploaded backup by main admin")
    return JSONResponse({"status": "restored"}, status_code=status.HTTP_200_OK)


__all__ = ["router"]
