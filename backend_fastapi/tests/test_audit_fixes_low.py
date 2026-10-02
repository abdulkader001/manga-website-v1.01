"""Fixes for the LOW findings of audit/full-audit-2026-10-02.md (F-86, F-87).

F-90 (server stats main-admin only) is covered in ``test_monitoring.py``.
"""

from __future__ import annotations

import asyncio
import gc

import pytest
from pydantic import ValidationError

from backend_fastapi.app.core.settings import Settings
from backend_fastapi.app.utils import swr_cache


def _settings(**overrides):
    base = dict(secret_key="x" * 12, jwt_secret_key="y" * 12)
    base.update(overrides)
    return Settings(**base)


# ---- F-86: background refreshes are kept alive until they finish ----


def test_background_refresh_survives_garbage_collection():
    finished = []

    async def refresh():
        await asyncio.sleep(0.01)
        gc.collect()
        finished.append(True)

    async def main():
        task = swr_cache._spawn(refresh())
        assert task in swr_cache._background_tasks
        del task
        gc.collect()
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert finished == [True]
    assert not swr_cache._background_tasks


def test_failed_background_refresh_is_logged(caplog):
    async def broken():
        raise RuntimeError("boom")

    async def main():
        swr_cache._spawn(broken())
        await asyncio.sleep(0.01)

    with caplog.at_level("WARNING", logger="backend_fastapi.swr_cache"):
        asyncio.run(main())
    assert any("swr_background_refresh_failed" in r.getMessage() for r in caplog.records)
    assert not swr_cache._background_tasks


# ---- F-87: only HMAC JWT algorithms are accepted ----


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512", "hs256", ""])
def test_hmac_algorithms_accepted(algorithm):
    settings = _settings(algorithm=algorithm)
    assert settings.algorithm in {"HS256", "HS384", "HS512"}


@pytest.mark.parametrize("algorithm", ["ES256", "RS256", "none", "EdDSA"])
def test_other_algorithms_refused(algorithm):
    with pytest.raises(ValidationError, match="ALGORITHM must be HS256, HS384 or HS512"):
        _settings(algorithm=algorithm)
