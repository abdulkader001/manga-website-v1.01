"""Roadmap item 14: pictures backup, restore and restore-test scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deployment"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("tar") is None,
    reason="needs bash and tar",
)


def _run(script: str, *args: str, **env: str):
    return subprocess.run(
        ["bash", str(DEPLOY / script), *args],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def storage(tmp_path):
    root = tmp_path / "storage"
    (root / "pages" / "1" / "2").mkdir(parents=True)
    (root / "covers").mkdir()
    (root / "pages" / "1" / "2" / "a.webp").write_bytes(b"page-a")
    (root / "covers" / "c.webp").write_bytes(b"cover")
    return root


def test_backup_then_restore_round_trips(storage, tmp_path):
    backups = tmp_path / "backups"
    made = _run("backup_storage.sh", STORAGE_DIR=str(storage), STORAGE_BACKUP_DIR=str(backups))
    assert made.returncode == 0, made.stderr
    archive = next(backups.glob("storage-*.tar"))

    target = tmp_path / "restored"
    restored = _run("restore_storage.sh", str(archive), str(target))
    assert restored.returncode == 0, restored.stderr
    assert (target / "pages" / "1" / "2" / "a.webp").read_bytes() == b"page-a"
    assert (target / "covers" / "c.webp").read_bytes() == b"cover"


def test_restore_refuses_a_non_empty_target(storage, tmp_path):
    backups = tmp_path / "backups"
    _run("backup_storage.sh", STORAGE_DIR=str(storage), STORAGE_BACKUP_DIR=str(backups))
    archive = next(backups.glob("storage-*.tar"))
    result = _run("restore_storage.sh", str(archive), str(storage))
    assert result.returncode != 0
    assert "not empty" in result.stderr


def test_verification_passes_on_a_healthy_volume(storage):
    result = _run("verify_storage_restore.sh", STORAGE_DIR=str(storage))
    assert result.returncode == 0, result.stderr
    assert "2 files identical" in result.stdout


def test_verification_fails_when_restore_differs(storage, tmp_path):
    """A restore that loses a file must be caught: corrupt the restore step."""
    broken = tmp_path / "deploy"
    shutil.copytree(DEPLOY, broken)
    # A restore that silently drops the covers folder.
    restore = broken / "restore_storage.sh"
    restore.write_text(restore.read_text().rstrip("\n") + '\nrm -rf "${TARGET}/covers"\n')
    result = subprocess.run(
        ["bash", str(broken / "verify_storage_restore.sh")],
        env={**os.environ, "STORAGE_DIR": str(storage)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "FAILED" in result.stderr


@pytest.mark.skipif(shutil.which("gpg") is None, reason="needs gpg")
def test_encrypted_round_trip(storage, tmp_path):
    backups = tmp_path / "backups"
    env = {"STORAGE_BACKUP_ENCRYPTION_PASSPHRASE": "correct horse"}
    made = _run("backup_storage.sh", STORAGE_DIR=str(storage), STORAGE_BACKUP_DIR=str(backups), **env)
    assert made.returncode == 0, made.stderr
    archive = next(backups.glob("storage-*.tar.gpg"))
    assert b"page-a" not in archive.read_bytes()
    target = tmp_path / "restored"
    assert _run("restore_storage.sh", str(archive), str(target), **env).returncode == 0
    assert (target / "covers" / "c.webp").read_bytes() == b"cover"
