"""Utilities for encrypting and decrypting user supplied integration secrets."""

from __future__ import annotations

import base64
import hashlib
import os
import structlog
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IntegrationKeyVault:
    """Encrypt and decrypt API keys supplied by admins or end users."""

    _fernet: MultiFernet

    @staticmethod
    def _fernet_for(secret: str) -> Fernet:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @classmethod
    def from_secret(
        cls, secret: str, previous: tuple[str, ...] | list[str] = ()
    ) -> "IntegrationKeyVault":
        """Build a vault from the current secret.

        ``previous`` holds older secrets (key rotation, roadmap item 16): they
        are only used to read values written before the rotation. New values
        are always written with ``secret``.
        """

        if not secret or not isinstance(secret, str):
            raise ValueError("IntegrationKeyVault requires a non-empty secret string")
        fernets = [cls._fernet_for(secret)]
        fernets.extend(cls._fernet_for(old) for old in previous if old)
        return cls(MultiFernet(fernets))

    @classmethod
    def from_env(cls) -> "IntegrationKeyVault | None":
        """Vault from ``INTEGRATIONS_SECRET`` (+ ``INTEGRATIONS_SECRET_PREVIOUS``).

        The previous secrets are comma-separated, newest first.
        """

        secret = os.getenv("INTEGRATIONS_SECRET")
        if not secret:
            return None
        previous = [
            part.strip()
            for part in (os.getenv("INTEGRATIONS_SECRET_PREVIOUS") or "").split(",")
            if part.strip()
        ]
        return cls.from_secret(secret, previous)

    def reencrypt(self, token: Optional[str]) -> Optional[str]:
        """Return ``token`` re-encrypted under the current secret.

        Returns ``None`` when the token cannot be read with any known secret.
        """

        if not token or not isinstance(token, str):
            return None
        try:
            return self._fernet.rotate(token.strip().encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return None

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
