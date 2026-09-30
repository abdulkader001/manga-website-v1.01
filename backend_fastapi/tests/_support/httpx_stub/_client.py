"""Minimal client defaults used by Starlette's TestClient."""

from __future__ import annotations


class UseClientDefault:
    """Sentinel mimicking httpx's UseClientDefault."""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "USE_CLIENT_DEFAULT"


USE_CLIENT_DEFAULT = UseClientDefault()
