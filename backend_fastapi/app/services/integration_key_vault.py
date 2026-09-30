"""Utilities for encrypting and decrypting user supplied integration secrets."""

from __future__ import annotations

import base64
import hashlib
import structlog
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IntegrationKeyVault:
    """Encrypt and decrypt API keys supplied by admins or end users."""

    _fernet: Fernet

    @classmethod
    def from_secret(cls, secret: str) -> "IntegrationKeyVault":
        if not secret or not isinstance(secret, str):
            raise ValueError("IntegrationKeyVault requires a non-empty secret string")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        return cls(Fernet(key))

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("Integration secrets must be strings")
        trimmed = value.strip()
        if not trimmed:
            return None
        token = self._fernet.encrypt(trimmed.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: Optional[str]) -> Optional[str]:
        if token is None:
            return None
        if not isinstance(token, str):
            logger.warning(
                "Expected encrypted secret to be a string; received %s", type(token)
            )
            return None
        token = token.strip()
        if not token:
            return None
        try:
            value = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken:
            logger.warning(
                "Unable to decrypt stored integration secret; token is invalid or stale."
            )
            return None
        return value.decode("utf-8")


__all__ = ["IntegrationKeyVault"]
