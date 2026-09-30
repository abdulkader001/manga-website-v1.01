"""Tests for circuit-breaker fallback behaviour and coverage (item 43)."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from backend_fastapi.app.utils.circuit_breaker import RedisCircuitBreaker


class _Req:
    class app:  # noqa: N801 - mimic FastAPI request.app.state
        class state:  # noqa: N801
            redis = None


def _run(coro):
    return asyncio.run(coro)


def test_execute_returns_result_on_success():
    cb = RedisCircuitBreaker()

    async def ok():
        return "translated"

    result = _run(cb.execute(_Req(), "translation", "prov", ok))
    assert result == "translated"


def test_execute_uses_fallback_on_failure():
    cb = RedisCircuitBreaker()

    async def boom():
        raise RuntimeError("provider down")

    async def fallback():
        return "last-known-good"

    result = _run(cb.execute(_Req(), "translation", "prov", boom, fallback=fallback))
    assert result == "last-known-good"


def test_execute_reraises_when_no_fallback():
    cb = RedisCircuitBreaker()

    async def boom():
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        _run(cb.execute(_Req(), "translation", "prov", boom))


def test_translation_and_ocr_routers_use_circuit_breaker():
    """Coverage check: both third-party provider paths are wrapped."""
    base = pathlib.Path(__file__).resolve().parent.parent / "app" / "api" / "routers"
    translation_src = (base / "translation.py").read_text(encoding="utf-8")
    ocr_src = (base / "ocr.py").read_text(encoding="utf-8")
    assert "cloud_circuit_breaker" in translation_src
    assert "cloud_circuit_breaker" in ocr_src
