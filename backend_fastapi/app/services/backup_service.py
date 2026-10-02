"""Storage & Backups: whole-site archives made, kept, shipped and restored.

One archive is a ``.zip`` holding:

* ``manifest.json`` -- when, which database, schema revision, what's inside;
* ``database.pgdump`` (PostgreSQL, ``pg_dump --format=custom``) or
  ``database.sqlite``;
* ``storage/...`` -- chapter pictures, covers, avatars and branding (optional;
  stored without recompression, they are already compressed images).

With a backup password set (Secret Vault ``BACKUP_PASSWORD``) the zip is
encrypted to ``.zip.enc`` (``backup_crypto``). Every archive has a sidecar
``<name>.json`` with its details, so the list survives a database restore
(the list is read from disk, not from the database being restored).

Archives live in ``BACKUP_DIR`` (default ``<storage>/backups``, never served
by nginx). The newest ``BACKUP_KEEP`` are kept; older ones are deleted here
and, when connected, in the S3-compatible storage too.

All long work runs in the Celery maintenance worker; one job at a time
(``.lock``), progress in ``.status.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import structlog
from sqlalchemy.engine import make_url

from . import backup_crypto
from .s3_storage import S3Client, S3Target, StorageError

logger = structlog.get_logger("backend_fastapi.backups")

FORMAT_VERSION = 1
LOCK_STALE_SECONDS = 6 * 3600
DUMP_TIMEOUT_SECONDS = 3 * 3600
MIN_FREE_BYTES = 512 * 1024 * 1024  # never fill the disk to the brim
ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.zip(\.enc)?$")
STORED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".pdf", ".zip", ".gz"}

DEFAULTS = {
    "schedule_enabled": True,
    "weekday": 6,  # Sunday
    "hour_utc": 3,
    "keep": 2,
    "include_images": True,
}


class BackupError(RuntimeError):
    """A backup action could not run (message is safe to show the admin)."""


# --------------------------------------------------------------------------
# Paths and settings
# --------------------------------------------------------------------------


def storage_root() -> Path:
    configured = os.getenv("STORAGE_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "storage"


def backup_dir() -> Path:
    configured = os.getenv("BACKUP_DIR")
    path = Path(configured) if configured else storage_root() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(float(os.getenv(name) or default))
    except ValueError:
        return default
    return min(high, max(low, value))


def settings() -> Dict[str, Any]:
    """Schedule and options (Secret Vault keys ``BACKUP_*``, else defaults)."""

    return {
        "schedule_enabled": _bool("BACKUP_SCHEDULE_ENABLED", DEFAULTS["schedule_enabled"]),
        "weekday": _int("BACKUP_WEEKDAY", DEFAULTS["weekday"], 0, 6),
        "hour_utc": _int("BACKUP_HOUR_UTC", DEFAULTS["hour_utc"], 0, 23),
        "keep": _int("BACKUP_KEEP", DEFAULTS["keep"], 1, 30),
        "include_images": _bool("BACKUP_INCLUDE_IMAGES", DEFAULTS["include_images"]),
        "encrypted": bool(os.getenv("BACKUP_PASSWORD")),
    }


def remote_target() -> Optional[S3Target]:
    endpoint = (os.getenv("BACKUP_S3_ENDPOINT") or "").strip()
    bucket = (os.getenv("BACKUP_S3_BUCKET") or "").strip()
    key_id = (os.getenv("BACKUP_S3_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("BACKUP_S3_SECRET_ACCESS_KEY") or "").strip()
    if not (endpoint and bucket and key_id and secret):
        return None
    return S3Target(
        endpoint=endpoint,
        bucket=bucket,
        access_key_id=key_id,
        secret_access_key=secret,
        region=(os.getenv("BACKUP_S3_REGION") or "auto").strip() or "auto",
        prefix=(os.getenv("BACKUP_S3_PREFIX") or "mangaworld-backups").strip().strip("/"),
    )


def _client(target: Optional[S3Target] = None) -> S3Client:
    target = target or remote_target()
    if target is None:
        raise BackupError("No storage is connected.")
    return S3Client(target)


# --------------------------------------------------------------------------
# Status and the one-job-at-a-time lock
# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status_path() -> Path:
    return backup_dir() / ".status.json"


def status() -> Dict[str, Any]:
    try:
        data = json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {"state": "idle"}
    if data.get("state") == "running":
        lock = backup_dir() / ".lock"
        if not lock.exists() or time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
            data["state"] = "failed"
            data["message"] = "The job stopped without finishing (the worker restarted?). Try again."
    return data


def _set_status(**fields: Any) -> None:
    current = status()
    current.update(fields)
    tmp = _status_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(current))
    os.replace(tmp, _status_path())


@contextmanager
def _job(action: str) -> Iterator[None]:
    lock = backup_dir() / ".lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_SECONDS:
        raise BackupError("Another backup or restore is already running. Wait for it to finish.")
    lock.write_text(str(os.getpid()))
    _set_status(state="running", action=action, started_at=_now(), finished_at=None, message="Starting…")
    try:
        yield
    except Exception as exc:
        message = str(exc) if isinstance(exc, (BackupError, StorageError, backup_crypto.BackupCryptoError)) else (
            f"Unexpected error: {exc.__class__.__name__}"
        )
        logger.exception("backup_job_failed", action=action)
        _set_status(state="failed", finished_at=_now(), message=message)
        raise
    else:
        _set_status(state="done", finished_at=_now())
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def begin(action: str) -> None:
    """Refuse up front (in the API) when a job is already running."""

    if status().get("state") == "running":
        raise BackupError("Another backup or restore is already running. Wait for it to finish.")
    _set_status(state="queued", action=action, message="Waiting for the background worker…", started_at=_now())


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".json")


def _check_name(name: str) -> str:
    if not ARCHIVE_RE.match(name or "") or "/" in name or ".." in name:
        raise BackupError("That is not a backup file name.")
    return name


def archive_path(name: str) -> Path:
    path = backup_dir() / _check_name(name)
    if not path.is_file():
        raise BackupError("That backup is not on this server.")
    return path


def _read_meta(path: Path) -> Dict[str, Any]:
    try:
        meta = json.loads(_sidecar(path).read_text())
    except (OSError, ValueError):
        meta = {}
    stat = path.stat()
    meta.setdefault("created_at", datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"))
    meta["name"] = path.name
    meta["size"] = stat.st_size
    meta["encrypted"] = path.name.endswith(".enc")
    return meta


def _write_meta(path: Path, meta: Dict[str, Any]) -> None:
    _sidecar(path).write_text(json.dumps(meta, indent=1))


def list_local() -> List[Dict[str, Any]]:
    items = [
        _read_meta(p)
        for p in backup_dir().iterdir()
        if p.is_file() and ARCHIVE_RE.match(p.name)
    ]
    return sorted(items, key=lambda m: m.get("created_at") or "", reverse=True)


def list_remote() -> List[Dict[str, Any]]:
    with _client() as client:
        items = [i for i in client.list() if ARCHIVE_RE.match(str(i["name"]))]
    return sorted(items, key=lambda i: str(i.get("modified") or ""), reverse=True)


def disk_usage() -> Dict[str, int]:
    usage = shutil.disk_usage(backup_dir())
    used = sum(p.stat().st_size for p in backup_dir().iterdir() if p.is_file())
    return {"free": usage.free, "total": usage.total, "backups": used}


# --------------------------------------------------------------------------
# Database dump / restore
# --------------------------------------------------------------------------


def _database_url() -> str:
    from ..core.db import DATABASE_URL

    return DATABASE_URL


def _db_kind(url: str) -> str:
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgresql"):
        return "postgresql"
    raise BackupError("Backups support PostgreSQL and SQLite databases only.")


def _sqlite_path(url: str) -> Path:
    database = make_url(url).database
    if not database or database == ":memory:":
        raise BackupError("This SQLite database is in memory; there is no file to back up.")
    return Path(database)


def _pg_params(url: str) -> Dict[str, str]:
    parsed = make_url(url)
    return {
        "host": parsed.host or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.database or "",
    }


def _run_pg(binary: str, args: List[str], params: Dict[str, str]) -> None:
    path = shutil.which(binary)
    if path is None:
        raise BackupError(f"'{binary}' is missing on this server. Rebuild the backend image (GUIDE 4.1).")
    try:
        result = subprocess.run(
            [path, *args],
            env=dict(os.environ, PGPASSWORD=params["password"]),
            capture_output=True,
            text=True,
            timeout=DUMP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{binary} took longer than {DUMP_TIMEOUT_SECONDS // 3600} hours.") from exc
    if result.returncode != 0:
        logger.error("pg_tool_failed", binary=binary, stderr=result.stderr[-2000:])
        raise BackupError(f"{binary} failed. The server log has the details.")


def dump_database(dest_dir: Path) -> Path:
    url = _database_url()
    kind = _db_kind(url)
    if kind == "sqlite":
        target = dest_dir / "database.sqlite"
        source = sqlite3.connect(f"file:{_sqlite_path(url)}?mode=ro", uri=True)
        try:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        return target
    target = dest_dir / "database.pgdump"
    params = _pg_params(url)
    _run_pg(
        "pg_dump",
        ["--format=custom", "--no-owner", "--no-privileges", "-h", params["host"], "-p", params["port"],
         "-U", params["user"], "-d", params["dbname"], "-f", str(target)],
        params,
    )
    return target


def restore_database(dump: Path) -> None:
    url = _database_url()
    kind = _db_kind(url)
    if dump.name.endswith(".sqlite") != (kind == "sqlite"):
        raise BackupError(
            f"This backup holds a {'SQLite' if dump.name.endswith('.sqlite') else 'PostgreSQL'} database "
            f"but this site runs {'SQLite' if kind == 'sqlite' else 'PostgreSQL'}."
        )
    if kind == "sqlite":
        source = sqlite3.connect(dump)
        try:
            dest = sqlite3.connect(_sqlite_path(url))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        return
    params = _pg_params(url)
    _run_pg(
        "pg_restore",
        ["--clean", "--if-exists", "--no-owner", "--no-privileges", "-h", params["host"], "-p", params["port"],
         "-U", params["user"], "-d", params["dbname"], str(dump)],
        params,
    )


def _alembic_revision() -> Optional[str]:
    try:
        from sqlalchemy import text

        from ..core.db import SessionLocal

        with SessionLocal() as session:
            return session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


def _storage_files(include_images: bool) -> Iterator[Path]:
    if not include_images:
        return
    root = storage_root()
    if not root.is_dir():
        return
    skip = {backup_dir().resolve(), (root / "geoip").resolve()}
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath).resolve()
        dirnames[:] = [d for d in dirnames if (current / d).resolve() not in skip and not d.startswith(".")]
        for filename in filenames:
            if filename.startswith(".") or filename.endswith((".part", ".tmp")):
                continue
            yield current / filename


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(*, trigger: str = "manual", include_images: Optional[bool] = None, actor_id: Optional[int] = None) -> Dict[str, Any]:
    """Make one archive, ship it to the connected storage, apply retention."""

    opts = settings()
    include = opts["include_images"] if include_images is None else bool(include_images)
    with _job("backup"):
        meta = _create(trigger=trigger, include_images=include, actor_id=actor_id)
        if trigger != "pre_restore":
            _ship(meta)
            prune(opts["keep"])
        return meta


def _create(*, trigger: str, include_images: bool, actor_id: Optional[int]) -> Dict[str, Any]:
    out_dir = backup_dir()
    root = storage_root().resolve()
    files = list(_storage_files(include_images))
    needed = sum(f.stat().st_size for f in files if f.exists())
    if shutil.disk_usage(out_dir).free < needed * 1.1 + MIN_FREE_BYTES:
        raise BackupError(
            "Not enough free disk for this backup "
            f"(needs about {needed // (1024 * 1024)} MB plus room to spare). "
            "Delete old backups, keep fewer, or turn off 'Include pictures'."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = "-pre-restore" if trigger == "pre_restore" else ""
    name = f"backup-{stamp}{suffix}.zip"
    password = os.getenv("BACKUP_PASSWORD") or ""

    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".work-") as work:
        work_dir = Path(work)
        _set_status(message="Saving the database…")
        dump = dump_database(work_dir)
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": _now(),
            "trigger": trigger,
            "database": dump.name,
            "alembic_revision": _alembic_revision(),
            "includes_images": include_images,
            "files": len(files),
            "created_by": actor_id,
        }
        zip_path = work_dir / name
        with zipfile.ZipFile(zip_path, "w", allowZip64=True) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=1))
            archive.write(dump, dump.name, compress_type=zipfile.ZIP_STORED if dump.suffix == ".pgdump" else zipfile.ZIP_DEFLATED)
            for index, path in enumerate(files, 1):
                if index % 500 == 0:
                    _set_status(message=f"Packing pictures… {index}/{len(files)}")
                try:
                    rel = path.relative_to(root).as_posix()
                except ValueError:
                    continue
                compress = zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                try:
                    archive.write(path, f"storage/{rel}", compress_type=compress)
                except FileNotFoundError:
                    continue  # deleted while packing
        final_name = name
        if password:
            _set_status(message="Encrypting…")
            encrypted = work_dir / (name + ".enc")
            backup_crypto.encrypt_file(zip_path, encrypted, password)
            zip_path.unlink()
            zip_path = encrypted
            final_name = encrypted.name
        _set_status(message="Checking the archive…")
        meta = {
            **manifest,
            "name": final_name,
            "sha256": _sha256(zip_path),
            "encrypted": bool(password),
        }
        final = out_dir / final_name
        os.replace(zip_path, final)
    _write_meta(final, meta)
    logger.info("backup_created", name=final_name, trigger=trigger, images=include_images)
    return _read_meta(final)


def _ship(meta: Dict[str, Any]) -> None:
    target = remote_target()
    if target is None:
        return
    path = backup_dir() / meta["name"]
    _set_status(message="Uploading to the connected storage…")
    try:
        with S3Client(target) as client:
            key = client.put_file(path, meta["name"])
            client.put_file(_sidecar(path), _sidecar(path).name)
        meta["remote"] = {"uploaded": True, "key": key, "at": _now()}
    except StorageError as exc:
        meta["remote"] = {"uploaded": False, "error": str(exc), "at": _now()}
        logger.warning("backup_upload_failed", name=meta["name"], error=str(exc))
    _write_meta(path, {k: v for k, v in meta.items() if k not in {"size"}})


def prune(keep: int) -> List[str]:
    """Keep the newest ``keep`` regular backups here and in the storage.

    Safety copies made before a restore and uploaded files are not counted
    and are kept until deleted by hand, so pruning never removes the backup
    someone is about to restore.
    """

    regular = [m for m in list_local() if m.get("trigger") in {"manual", "scheduled"}]
    removed: List[str] = []
    for meta in regular[keep:]:
        delete_local(meta["name"])
        removed.append(meta["name"])
    target = remote_target()
    if target is not None:
        try:
            with S3Client(target) as client:
                remote = sorted(
                    (i for i in client.list() if ARCHIVE_RE.match(str(i["name"])) and "-pre-restore" not in str(i["name"])),
                    key=lambda i: str(i["name"]),
                    reverse=True,
                )
                for item in remote[keep:]:
                    client.delete(str(item["name"]))
                    try:
                        client.delete(str(item["name"]) + ".json")
                    except StorageError:
                        pass
        except StorageError as exc:
            logger.warning("backup_remote_prune_failed", error=str(exc))
    return removed


def delete_local(name: str) -> None:
    path = archive_path(name)
    path.unlink()
    try:
        _sidecar(path).unlink()
    except OSError:
        pass


def is_due(now: Optional[datetime] = None) -> bool:
    """Weekly schedule: the chosen weekday and hour, once a week."""

    opts = settings()
    if not opts["schedule_enabled"]:
        return False
    now = now or datetime.now(timezone.utc)
    if now.weekday() != opts["weekday"] or now.hour != opts["hour_utc"]:
        return False
    for meta in list_local():
        if meta.get("trigger") != "scheduled":
            continue
        try:
            made = datetime.fromisoformat(str(meta["created_at"]))
        except (KeyError, ValueError):
            continue
        if made.tzinfo is None:
            made = made.replace(tzinfo=timezone.utc)
        if (now - made).total_seconds() < 6 * 86400:
            return False
    return True


# --------------------------------------------------------------------------
# Bring a backup onto this server: browser upload or from the storage
# --------------------------------------------------------------------------


def _safe_upload_name(filename: str) -> str:
    base = Path(filename or "").name
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base).lstrip(".-") or "backup.zip"
    if not (base.endswith(".zip") or base.endswith(".zip.enc")):
        raise BackupError("Upload a backup made by this site (.zip or .zip.enc).")
    stem = base[: -len(".zip.enc")] if base.endswith(".zip.enc") else base[:-4]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stem[:80]}-uploaded-{stamp}" + (".zip.enc" if base.endswith(".enc") else ".zip")
    return _check_name(name)


def _looks_like_backup(path: Path) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(8)
    return head == backup_crypto.MAGIC or head[:4] == b"PK\x03\x04"


def accept_upload(tmp_path: Path, filename: str, actor_id: Optional[int]) -> Dict[str, Any]:
    if not _looks_like_backup(tmp_path):
        tmp_path.unlink(missing_ok=True)
        raise BackupError("That file is not a backup made by this site.")
    name = _safe_upload_name(filename)
    final = backup_dir() / name
    os.replace(tmp_path, final)
    _write_meta(final, {"trigger": "uploaded", "created_at": _now(), "uploaded_by": actor_id})
    return _read_meta(final)


def fetch_remote(name: str) -> Dict[str, Any]:
    _check_name(name)
    with _job("fetch"):
        dest = backup_dir() / name
        if dest.exists():
            raise BackupError("That backup is already on this server.")
        _set_status(message="Downloading from the storage…")
        with _client() as client:
            client.get_to_file(name, dest)
            meta: Dict[str, Any] = {}
            try:
                side = backup_dir() / f".{name}.json.tmp"
                client.get_to_file(name + ".json", side)
                meta = json.loads(side.read_text())
                side.unlink()
            except (StorageError, OSError, ValueError):
                pass
        meta.update({"fetched_at": _now(), "trigger": meta.get("trigger") or "fetched"})
        if not _looks_like_backup(dest):
            dest.unlink()
            raise BackupError("The file in the storage is not a backup made by this site.")
        _write_meta(dest, meta)
        return _read_meta(dest)


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------


def _safe_member(name: str) -> bool:
    parts = Path(name).parts
    return bool(parts) and not name.startswith("/") and ".." not in parts and "\\" not in name


def restore(name: str, *, password: Optional[str] = None, actor_id: Optional[int] = None) -> Dict[str, Any]:
    """Replace the database (and pictures, when the backup has them) with ``name``.

    A database-only safety copy of the current site is made first, so a wrong
    choice can be undone from the list.
    """

    source = archive_path(name)
    with _job("restore"):
        with tempfile.TemporaryDirectory(dir=backup_dir(), prefix=".restore-") as work:
            work_dir = Path(work)
            zip_path = source
            if backup_crypto.is_encrypted(source):
                _set_status(message="Decrypting…")
                zip_path = work_dir / "archive.zip"
                backup_crypto.decrypt_file(source, zip_path, password or os.getenv("BACKUP_PASSWORD") or "")
            elif meta_hash := _read_meta(source).get("sha256"):
                _set_status(message="Checking the archive…")
                if _sha256(source) != meta_hash:
                    raise BackupError("This backup file is damaged (its checksum doesn't match).")

            try:
                archive = zipfile.ZipFile(zip_path)
            except zipfile.BadZipFile as exc:
                raise BackupError("This file is not a readable backup archive.") from exc
            with archive:
                names = archive.namelist()
                if "manifest.json" not in names:
                    raise BackupError("This archive has no manifest: it was not made by this site.")
                manifest = json.loads(archive.read("manifest.json"))
                if int(manifest.get("format") or 0) > FORMAT_VERSION:
                    raise BackupError("This backup was made by a newer version of the site. Update first.")
                bad = [n for n in names if not _safe_member(n)]
                if bad:
                    raise BackupError("This archive contains unsafe file paths and was refused.")
                dump_name = manifest.get("database")
                if dump_name not in names or dump_name not in {"database.pgdump", "database.sqlite"}:
                    raise BackupError("This archive has no database in it.")

                _set_status(message="Making a safety copy of the current database…")
                _create(trigger="pre_restore", include_images=False, actor_id=actor_id)

                _set_status(message="Restoring the database…")
                dump = work_dir / dump_name
                with archive.open(dump_name) as src, open(dump, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                restore_database(dump)
                dump.unlink()

                pictures = [n for n in names if n.startswith("storage/") and not n.endswith("/")]
                root = storage_root().resolve()
                for index, member in enumerate(pictures, 1):
                    if index % 500 == 0:
                        _set_status(message=f"Restoring pictures… {index}/{len(pictures)}")
                    target = (root / member[len("storage/"):]).resolve()
                    if root not in target.parents:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
        logger.info("backup_restored", name=name, by=actor_id)
        result = {
            "name": name,
            "restored_at": _now(),
            "pictures": len(pictures),
            "alembic_revision": manifest.get("alembic_revision"),
        }
        _set_status(message="Restored. Restart the site so it upgrades the restored database if needed.", result=result)
        return result


__all__ = [
    "BackupError",
    "accept_upload",
    "archive_path",
    "backup_dir",
    "begin",
    "create_backup",
    "delete_local",
    "disk_usage",
    "fetch_remote",
    "is_due",
    "list_local",
    "list_remote",
    "prune",
    "remote_target",
    "restore",
    "settings",
    "status",
    "storage_root",
]
