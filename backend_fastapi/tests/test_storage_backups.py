"""Storage & Backups: archives, encryption, retention, S3 storage, restore, API."""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import requests

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import backup_crypto, backup_service, s3_storage
from backend_fastapi.app.services.s3_storage import S3Client, S3Target, StorageError

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """A fake site: storage with pictures, a backup folder, a fake database."""

    storage = tmp_path / "storage"
    (storage / "pages" / "12").mkdir(parents=True)
    (storage / "covers").mkdir()
    (storage / "pages" / "12" / "001.webp").write_bytes(b"RIFF-page-1" * 50)
    (storage / "pages" / "12" / "002.webp").write_bytes(b"RIFF-page-2" * 50)
    (storage / "covers" / "12.jpg").write_bytes(b"\xff\xd8cover")
    monkeypatch.setenv("STORAGE_ROOT", str(storage))
    monkeypatch.setenv("BACKUP_DIR", str(storage / "backups"))
    for key in ("BACKUP_PASSWORD", "BACKUP_KEEP", "BACKUP_S3_ENDPOINT", "BACKUP_S3_BUCKET",
                "BACKUP_S3_ACCESS_KEY_ID", "BACKUP_S3_SECRET_ACCESS_KEY", "BACKUP_S3_PREFIX",
                "BACKUP_INCLUDE_IMAGES", "BACKUP_SCHEDULE_ENABLED", "BACKUP_WEEKDAY", "BACKUP_HOUR_UTC"):
        monkeypatch.delenv(key, raising=False)

    def fake_dump(dest_dir: Path) -> Path:
        out = dest_dir / "database.sqlite"
        out.write_bytes(b"SQLite format 3\x00" + b"rows" * 100)
        return out

    restored: list[bytes] = []
    monkeypatch.setattr(backup_service, "dump_database", fake_dump)
    monkeypatch.setattr(backup_service, "restore_database", lambda dump: restored.append(dump.read_bytes()))
    monkeypatch.setattr(backup_service, "_alembic_revision", lambda: "20261012_overlay_text_scale")
    return {"storage": storage, "restored": restored}


class _Adapter(requests.adapters.BaseAdapter):
    """Answers requests from a handler(request) -> (status, headers, body)."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def send(self, request, **_kwargs):
        status, headers, body = self.handler(request)
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response.raw = io.BytesIO(body)
        response.request = request
        response.url = request.url
        return response

    def close(self):
        pass


def _session(handler) -> requests.Session:
    session = requests.Session()
    session.mount("https://", _Adapter(handler))
    return session


def _reply(status: int, text: str = "", content: bytes | None = None, headers=None):
    return status, headers or {}, content if content is not None else text.encode()


class FakeS3:
    """In-memory S3: enough of the API for backups, checking every request is signed."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, dict[int, bytes]] = {}
        self.requests: list[str] = []

    def handler(self, request):
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/")
        assert "x-amz-date" in request.headers and "x-amz-content-sha256" in request.headers
        url = urlparse(request.url)
        query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        _, bucket, *rest = url.path.split("/", 2)
        key = unquote(rest[0]) if rest else ""
        self.requests.append(f"{request.method} {key} {sorted(query)}")
        body = request.body
        if hasattr(body, "read"):
            body = body.read()
        body = body.encode() if isinstance(body, str) else (body or b"")
        if request.method == "PUT" and "uploadId" in query:
            self.uploads[query["uploadId"]][int(query["partNumber"])] = body
            return _reply(200, headers={"etag": f'"p{query["partNumber"]}"'})
        if request.method == "PUT":
            self.objects[key] = body
            return _reply(200, headers={"etag": '"x"'})
        if request.method == "POST" and "uploads" in query:
            upload_id = uuid.uuid4().hex
            self.uploads[upload_id] = {}
            return _reply(200, f"<InitiateMultipartUploadResult><UploadId>{upload_id}</UploadId></InitiateMultipartUploadResult>")
        if request.method == "POST" and "uploadId" in query:
            parts = self.uploads.pop(query["uploadId"])
            self.objects[key] = b"".join(parts[n] for n in sorted(parts))
            return _reply(200, "<CompleteMultipartUploadResult/>")
        if request.method == "GET" and query.get("list-type") == "2":
            prefix = query.get("prefix", "")
            items = "".join(
                f"<Contents><Key>{k}</Key><Size>{len(v)}</Size><LastModified>2026-10-02T00:00:00Z</LastModified></Contents>"
                for k, v in sorted(self.objects.items()) if k.startswith(prefix)
            )
            return _reply(200, f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{items}<IsTruncated>false</IsTruncated></ListBucketResult>')
        if request.method == "GET":
            if key not in self.objects:
                return _reply(404, "<Error><Code>NoSuchKey</Code></Error>")
            return _reply(200, content=self.objects[key])
        if request.method == "DELETE":
            if "uploadId" in query:
                self.uploads.pop(query["uploadId"], None)
            else:
                self.objects.pop(key, None)
            return _reply(204)
        return _reply(400)


TARGET = S3Target(endpoint="https://s3.example.test", bucket="bk", access_key_id="AKID", secret_access_key="SECRET", region="auto", prefix="site")


@pytest.fixture()
def fake_s3(monkeypatch):
    fake = FakeS3()
    factory = lambda target, **_: S3Client(target, session=_session(fake.handler))  # noqa: E731
    monkeypatch.setattr(backup_service, "S3Client", factory)
    from backend_fastapi.app.api.routers import backups_admin

    monkeypatch.setattr(backups_admin, "S3Client", factory)
    return fake


def _connect(monkeypatch):
    monkeypatch.setenv("BACKUP_S3_ENDPOINT", TARGET.endpoint)
    monkeypatch.setenv("BACKUP_S3_BUCKET", TARGET.bucket)
    monkeypatch.setenv("BACKUP_S3_ACCESS_KEY_ID", TARGET.access_key_id)
    monkeypatch.setenv("BACKUP_S3_SECRET_ACCESS_KEY", TARGET.secret_access_key)
    monkeypatch.setenv("BACKUP_S3_PREFIX", TARGET.prefix)


# --------------------------------------------------------------------------
# Archives
# --------------------------------------------------------------------------


def test_backup_holds_database_pictures_and_manifest(site):
    meta = backup_service.create_backup()
    path = backup_service.backup_dir() / meta["name"]
    assert re.match(r"backup-\d{8}-\d{6}\.zip$", meta["name"])
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        # Pictures are stored as-is, not recompressed.
        assert archive.getinfo("storage/pages/12/001.webp").compress_type == zipfile.ZIP_STORED
    assert {"manifest.json", "database.sqlite", "storage/pages/12/001.webp", "storage/covers/12.jpg"} <= names
    assert not any(n.startswith("storage/backups") for n in names)  # never backs up its backups
    assert manifest["alembic_revision"] == "20261012_overlay_text_scale"
    assert meta["sha256"] and meta["includes_images"] is True
    assert backup_service.status()["state"] == "done"


def test_pictures_can_be_left_out(site):
    meta = backup_service.create_backup(include_images=False)
    with zipfile.ZipFile(backup_service.backup_dir() / meta["name"]) as archive:
        assert not [n for n in archive.namelist() if n.startswith("storage/")]


def test_keeps_only_the_newest(site, monkeypatch):
    names = []
    for i in range(3):
        meta = backup_service.create_backup()
        new = meta["name"].replace(".zip", f"-{i}.zip")
        path = backup_service.backup_dir() / meta["name"]
        os.replace(path, path.with_name(new))
        os.replace(path.with_name(path.name + ".json"), path.with_name(new + ".json"))
        side = json.loads(path.with_name(new + ".json").read_text())
        side["created_at"] = f"2026-10-0{i + 1}T00:00:00+00:00"
        path.with_name(new + ".json").write_text(json.dumps(side))
        names.append(new)
    backup_service.prune(2)
    assert [m["name"] for m in backup_service.list_local()] == [names[2], names[1]]


def test_not_enough_disk_is_refused(site, monkeypatch):
    monkeypatch.setattr(backup_service.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10, "total": 10})())
    with pytest.raises(backup_service.BackupError, match="Not enough free disk"):
        backup_service.create_backup()
    assert backup_service.status()["state"] == "failed"
    assert not (backup_service.backup_dir() / ".lock").exists()


def test_weekly_schedule(site, monkeypatch):
    monkeypatch.setenv("BACKUP_WEEKDAY", "6")
    monkeypatch.setenv("BACKUP_HOUR_UTC", "3")
    sunday_3am = datetime(2026, 10, 4, 3, 10, tzinfo=timezone.utc)
    assert backup_service.is_due(sunday_3am)
    assert not backup_service.is_due(sunday_3am.replace(hour=4))
    monkeypatch.setenv("BACKUP_SCHEDULE_ENABLED", "false")
    assert not backup_service.is_due(sunday_3am)


# --------------------------------------------------------------------------
# Encryption
# --------------------------------------------------------------------------


def test_encryption_round_trip_and_refusals(tmp_path):
    src = tmp_path / "a.zip"
    data = os.urandom(backup_crypto.CHUNK * 2 + 12345)
    src.write_bytes(data)
    enc = tmp_path / "a.zip.enc"
    backup_crypto.encrypt_file(src, enc, "correct horse battery")
    assert backup_crypto.is_encrypted(enc) and data[:64] not in enc.read_bytes()

    out = tmp_path / "out.zip"
    backup_crypto.decrypt_file(enc, out, "correct horse battery")
    assert out.read_bytes() == data

    with pytest.raises(backup_crypto.BackupCryptoError, match="Wrong backup password"):
        backup_crypto.decrypt_file(enc, tmp_path / "x", "wrong password!")
    blob = enc.read_bytes()
    (tmp_path / "cut.enc").write_bytes(blob[: len(blob) // 2])
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_crypto.decrypt_file(tmp_path / "cut.enc", tmp_path / "y", "correct horse battery")
    flipped = bytearray(blob)
    flipped[-20] ^= 1
    (tmp_path / "flip.enc").write_bytes(bytes(flipped))
    with pytest.raises(backup_crypto.BackupCryptoError, match="damaged"):
        backup_crypto.decrypt_file(tmp_path / "flip.enc", tmp_path / "z", "correct horse battery")
    assert not (tmp_path / "z").exists()


def test_password_encrypts_backups_and_restore_needs_it(site, monkeypatch):
    monkeypatch.setenv("BACKUP_PASSWORD", "a long backup password")
    meta = backup_service.create_backup()
    assert meta["name"].endswith(".zip.enc") and meta["encrypted"]
    monkeypatch.delenv("BACKUP_PASSWORD")
    with pytest.raises(backup_crypto.BackupCryptoError):
        backup_service.restore(meta["name"])
    backup_service.restore(meta["name"], password="a long backup password")
    assert site["restored"] and site["restored"][-1].startswith(b"SQLite format 3")


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------


def test_restore_brings_back_pictures_and_makes_a_safety_copy(site):
    meta = backup_service.create_backup()
    picture = site["storage"] / "pages" / "12" / "001.webp"
    picture.unlink()
    result = backup_service.restore(meta["name"], actor_id=1)
    assert picture.read_bytes() == b"RIFF-page-1" * 50
    assert result["pictures"] == 3
    triggers = {m.get("trigger") for m in backup_service.list_local()}
    assert "pre_restore" in triggers


def test_restore_refuses_unsafe_or_foreign_archives(site):
    folder = backup_service.backup_dir()
    evil = folder / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": 1, "database": "database.sqlite"}))
        archive.writestr("database.sqlite", b"SQLite format 3\x00")
        archive.writestr("storage/../../escape.txt", b"x")
    with pytest.raises(backup_service.BackupError, match="unsafe"):
        backup_service.restore("evil.zip")
    assert not (site["storage"].parent / "escape.txt").exists()

    foreign = folder / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as archive:
        archive.writestr("readme.txt", b"hello")
    with pytest.raises(backup_service.BackupError, match="manifest"):
        backup_service.restore("foreign.zip")
    assert not site["restored"]


def test_restore_refuses_a_damaged_file(site):
    meta = backup_service.create_backup()
    path = backup_service.backup_dir() / meta["name"]
    blob = bytearray(path.read_bytes())
    blob[len(blob) // 2] ^= 1
    path.write_bytes(bytes(blob))
    with pytest.raises(backup_service.BackupError, match="damaged"):
        backup_service.restore(meta["name"])


def test_one_job_at_a_time(site):
    (backup_service.backup_dir() / ".lock").write_text("1")
    with pytest.raises(backup_service.BackupError, match="already running"):
        backup_service.create_backup()


# --------------------------------------------------------------------------
# S3-compatible storage
# --------------------------------------------------------------------------


def test_s3_single_and_multipart_upload_list_get_delete(tmp_path, fake_s3, monkeypatch):
    monkeypatch.setattr(s3_storage, "PART_SIZE", 1024)
    small, big = tmp_path / "small.zip", tmp_path / "big.zip"
    small.write_bytes(b"s" * 100)
    big.write_bytes(os.urandom(3000))
    client = backup_service.S3Client(TARGET)
    client.test()
    client.put_file(small, "small.zip")
    client.put_file(big, "big.zip")
    assert fake_s3.objects["site/big.zip"] == big.read_bytes()
    assert any("partNumber" in r for r in fake_s3.requests)
    assert {i["name"] for i in client.list()} == {"small.zip", "big.zip"}
    client.get_to_file("big.zip", tmp_path / "back.zip")
    assert (tmp_path / "back.zip").read_bytes() == big.read_bytes()
    client.delete("small.zip")
    assert "site/small.zip" not in fake_s3.objects
    with pytest.raises(StorageError, match="isn't in the storage"):
        client.get_to_file("missing.zip", tmp_path / "m.zip")


def test_backups_are_shipped_pruned_and_fetched(site, fake_s3, monkeypatch):
    _connect(monkeypatch)
    monkeypatch.setenv("BACKUP_KEEP", "1")
    first = backup_service.create_backup()
    assert first.get("remote", {}).get("uploaded") is True
    assert f"site/{first['name']}" in fake_s3.objects
    # A second, newer backup replaces the first here and in the storage.
    fake_s3.objects[f"site/{first['name']}"] = fake_s3.objects.pop(f"site/{first['name']}")
    second_name = "backup-29990101-000000.zip"
    fake_s3.objects[f"site/{second_name}"] = (backup_service.backup_dir() / first["name"]).read_bytes()
    backup_service.prune(1)
    assert [k for k in fake_s3.objects if k.endswith(".zip")] == [f"site/{second_name}"]

    meta = backup_service.fetch_remote(second_name)
    assert (backup_service.backup_dir() / second_name).exists() and meta["trigger"] == "fetched"


def test_bad_storage_keys_give_a_plain_message(tmp_path):
    session = _session(lambda r: _reply(403, "<Error><Code>SignatureDoesNotMatch</Code></Error>"))
    with pytest.raises(StorageError, match="secret access key is wrong"):
        S3Client(TARGET, session=session).test()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def _user(role: UserRole, main: bool = False) -> dict:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        user = User(
            email=f"bk-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=role,
            is_main_admin=main,
            is_secondary_admin=role == UserRole.SECONDARY,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_only_the_main_admin_can_open_it(fastapi_client, site):
    assert fastapi_client.get("/api/v1/admin/backups").status_code == 401
    assert fastapi_client.get("/api/v1/admin/backups", headers=_user(UserRole.SECONDARY)).status_code == 403
    assert fastapi_client.get("/api/v1/admin/backups", headers=_user(UserRole.USER)).status_code == 403
    response = fastapi_client.get("/api/v1/admin/backups", headers=_user(UserRole.ADMIN, main=True))
    assert response.status_code == 200
    assert response.json()["storage"]["connected"] is False


def test_api_backup_download_upload_and_restore(fastapi_client, site):
    admin = _user(UserRole.ADMIN, main=True)
    assert fastapi_client.post("/api/v1/admin/backups/run", json={}, headers=admin).status_code == 202
    listing = fastapi_client.get("/api/v1/admin/backups", headers=admin).json()
    name = listing["backups"][0]["name"]

    download = fastapi_client.get(f"/api/v1/admin/backups/files/{name}", headers=admin)
    assert download.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(download.content)).read("manifest.json")
    assert fastapi_client.get("/api/v1/admin/backups/files/..%2F..%2Fetc%2Fpasswd", headers=admin).status_code in (404, 422)

    uploaded = fastapi_client.post(
        "/api/v1/admin/backups/upload?filename=from-laptop.zip", content=download.content, headers=admin
    )
    assert uploaded.status_code == 200, uploaded.text
    up_name = uploaded.json()["backup"]["name"]
    assert "uploaded" in up_name
    junk = fastapi_client.post("/api/v1/admin/backups/upload?filename=notes.zip", content=b"hello", headers=admin)
    assert junk.status_code == 400

    no_confirm = fastapi_client.post(f"/api/v1/admin/backups/files/{up_name}/restore", json={"confirm": "yes"}, headers=admin)
    assert no_confirm.status_code == 400
    ok = fastapi_client.post(f"/api/v1/admin/backups/files/{up_name}/restore", json={"confirm": "RESTORE"}, headers=admin)
    assert ok.status_code == 202, ok.text
    assert site["restored"]


def test_connecting_storage_tests_it_first_and_hides_the_secret(fastapi_client, site, fake_s3, monkeypatch):
    from backend_fastapi.app.services import secret_vault

    admin = _user(UserRole.ADMIN, main=True)
    body = {
        "endpoint": TARGET.endpoint,
        "bucket": TARGET.bucket,
        "region": "auto",
        "prefix": "site",
        "access_key_id": "AKID",
        "secret_access_key": "SECRET",
    }
    try:
        response = fastapi_client.put("/api/v1/admin/backups/storage", json=body, headers=admin)
        assert response.status_code == 200, response.text
        assert response.json()["storage"]["connected"] is True
        assert "SECRET" not in response.text
        assert any(r.startswith("PUT site/.connection-test-") for r in fake_s3.requests)

        refused = lambda r: _reply(403, "<Error><Code>AccessDenied</Code></Error>")  # noqa: E731
        from backend_fastapi.app.api.routers import backups_admin

        monkeypatch.setattr(backups_admin, "S3Client", lambda t, **_: S3Client(t, session=_session(refused)))
        bad = fastapi_client.put("/api/v1/admin/backups/storage", json={**body, "bucket": "other"}, headers=admin)
        assert bad.status_code == 400 and "allowed" in bad.json()["error"]["message"]
        assert os.environ.get("BACKUP_S3_BUCKET") == TARGET.bucket  # the failed one was not saved

        assert fastapi_client.delete("/api/v1/admin/backups/storage", headers=admin).json()["storage"]["connected"] is False
    finally:
        with SessionLocal() as session:
            for key in backups_admin_keys():
                try:
                    secret_vault.remove(session, key)
                except Exception:
                    pass


def backups_admin_keys():
    from backend_fastapi.app.api.routers.backups_admin import STORAGE_KEYS

    return STORAGE_KEYS


def test_real_sqlite_dump_and_restore_round_trip(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "site.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE manga (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO manga (title) VALUES ('Solo Leveling')")
    monkeypatch.setattr(backup_service, "_database_url", lambda: f"sqlite:///{db}")
    dump = backup_service.dump_database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM manga")
    backup_service.restore_database(dump)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT title FROM manga").fetchall() == [("Solo Leveling",)]
    with pytest.raises(backup_service.BackupError, match="PostgreSQL"):
        backup_service.restore_database(tmp_path / "database.pgdump")
