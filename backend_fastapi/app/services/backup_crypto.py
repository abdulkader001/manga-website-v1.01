"""Password encryption for backup archives, streamed so size doesn't matter.

Format (``.enc`` files)::

    MAGIC (8) | salt (16) | nonce prefix (4)
    then records: final flag (1) | length (4, big-endian) | AES-256-GCM ciphertext

The key comes from the password with scrypt. Each 1 MB chunk is sealed with
a nonce of ``prefix + chunk counter`` and authenticated together with the
header, its counter and whether it is the last chunk. So a wrong password, a
flipped bit, reordered chunks or a cut-off file are all refused instead of
restoring damaged data.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"MWBKENC1"
CHUNK = 1024 * 1024
_SCRYPT_N = 2**15


class BackupCryptoError(ValueError):
    """Wrong password or damaged file (message is safe to show)."""


def is_encrypted(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def _key(password: str, salt: bytes) -> bytes:
    if not password:
        raise BackupCryptoError("This backup is encrypted: enter its backup password.")
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=8, p=1).derive(password.encode("utf-8"))


def _aad(header: bytes, counter: int, final: bool) -> bytes:
    return header + struct.pack(">QB", counter, 1 if final else 0)


def encrypt_file(src: Path, dest: Path, password: str) -> None:
    salt = os.urandom(16)
    prefix = os.urandom(4)
    header = MAGIC + salt + prefix
    aead = AESGCM(_key(password, salt))
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        fout.write(header)
        counter = 0
        chunk = fin.read(CHUNK)
        while True:
            following = fin.read(CHUNK)
            final = not following
            nonce = prefix + struct.pack(">Q", counter)
            sealed = aead.encrypt(nonce, chunk, _aad(header, counter, final))
            fout.write(struct.pack(">BI", 1 if final else 0, len(sealed)))
            fout.write(sealed)
            if final:
                break
            chunk = following
            counter += 1


def _read_exact(fh: BinaryIO, n: int) -> bytes:
    data = fh.read(n)
    if len(data) != n:
        raise BackupCryptoError("The backup file is cut off or damaged.")
    return data


def decrypt_file(src: Path, dest: Path, password: str) -> None:
    with open(src, "rb") as fin:
        header = _read_exact(fin, len(MAGIC) + 20)
        if not header.startswith(MAGIC):
            raise BackupCryptoError("This is not an encrypted backup.")
        salt, prefix = header[8:24], header[24:28]
        aead = AESGCM(_key(password, salt))
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with open(tmp, "wb") as fout:
                counter = 0
                while True:
                    final, length = struct.unpack(">BI", _read_exact(fin, 5))
                    if length > CHUNK + 16:
                        raise BackupCryptoError("The backup file is damaged.")
                    sealed = _read_exact(fin, length)
                    nonce = prefix + struct.pack(">Q", counter)
                    try:
                        fout.write(aead.decrypt(nonce, sealed, _aad(header, counter, bool(final))))
                    except InvalidTag:
                        if counter == 0:
                            raise BackupCryptoError("Wrong backup password (or a damaged file).") from None
                        raise BackupCryptoError("The backup file is damaged.") from None
                    if final:
                        if fin.read(1):
                            raise BackupCryptoError("The backup file has extra data after its end.")
                        break
                    counter += 1
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()


__all__ = ["encrypt_file", "decrypt_file", "is_encrypted", "BackupCryptoError", "MAGIC"]
