"""Startup and shutdown helpers for infrastructure components."""

from __future__ import annotations

import asyncio
import structlog
from urllib.parse import urlparse

from fastapi import FastAPI
import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..core.celery_app import celery_app
from ..core.db import check_connection_budget, engine
from ..core.settings import settings

logger = structlog.get_logger("backend_fastapi.app")


async def check_database_connection() -> bool:
    """Attempt to validate the configured database connection."""

    loop = asyncio.get_running_loop()

    def _ping() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    try:
        await loop.run_in_executor(None, _ping)
    except SQLAlchemyError:
        logger.warning("Database connectivity check failed", exc_info=True)
        return False
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Unexpected error during database connectivity check")
        return False

    logger.info("Database connectivity verified")

    # F-85: surface a pool/worker/max_connections mismatch at startup rather
    # than letting it show up as mysteriously slow requests under load.
    try:
        await loop.run_in_executor(None, check_connection_budget)
    except Exception:  # pragma: no cover - advisory check, never fatal
        logger.debug("Connection budget check failed", exc_info=True)

    return True


def _redis_required() -> bool:
    return bool(getattr(settings, "redis_required", False))


async def initialize_redis(app: FastAPI, redis_url: str | None) -> Redis | None:
    """Initialize and register Redis client when configured and reachable.

    Item 30: when ``REDIS_REQUIRED`` is set, an unconfigured or unreachable Redis
    fails startup loudly instead of silently degrading to weaker in-process
    behaviour.
    """

    if not redis_url:
        if _redis_required():
            raise RuntimeError(
                "REDIS_REQUIRED is set but no Redis URL is configured "
                "(set REDIS_URL / CELERY_BROKER_URL)."
            )
        logger.info("Redis URL not configured; skipping Redis client initialization")
        return None

    scheme = urlparse(redis_url).scheme
    if scheme not in {"redis", "rediss", "unix"}:
        if _redis_required():
            raise RuntimeError(
                f"REDIS_REQUIRED is set but Redis URL scheme '{scheme}' is not a "
                "runtime Redis connection."
            )
        logger.info(
            "Redis URL scheme '%s' is not supported for runtime connections; skipping Redis client",
            scheme or "",
        )
        return None

    client = Redis.from_url(redis_url)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - depends on environment
        await client.close()
        if _redis_required():
            raise RuntimeError(
                f"REDIS_REQUIRED is set but Redis at {redis_url} is unreachable: {exc}"
            ) from exc
        logger.warning("Unable to connect to Redis at %s", redis_url, exc_info=True)
        return None

    app.state.redis = client
    logger.info("Redis client initialised for %s", redis_url)
    return client


async def shutdown_redis(app: FastAPI) -> None:
    """Close Redis client stored on app state."""

    client = getattr(app.state, "redis", None)
    if client is None:
        return
    try:
        await client.close()
    finally:
        app.state.redis = None


async def initialize_celery(app: FastAPI) -> object | None:
    """Initialize Celery broker connection for health visibility."""

    loop = asyncio.get_running_loop()

    def _connect():
        connection = celery_app.connection()
        connection.connect()
        return connection

    try:
        connection = await loop.run_in_executor(None, _connect)
    except Exception:  # pragma: no cover - depends on broker availability
        logger.warning("Unable to establish Celery broker connection", exc_info=True)
        return None

    app.state.celery_connection = connection
    logger.info("Celery broker connection established")
    return connection


async def shutdown_celery(app: FastAPI) -> None:
    """Release Celery broker connection stored on app state."""

    connection = getattr(app.state, "celery_connection", None)
    if connection is None:
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, connection.release)
    app.state.celery_connection = None


async def initialize_http_client(app: FastAPI) -> httpx.AsyncClient:
    """Initialize a global HTTP client for outgoing requests."""

    # Use the 10s timeout from the OCR router's IMAGE_FETCH_TIMEOUT
    client = httpx.AsyncClient(timeout=10.0)
    app.state.http_client = client
    logger.info("Global HTTPX client initialized")
    return client


async def shutdown_http_client(app: FastAPI) -> None:
    """Close the global HTTP client stored on app state."""

    client = getattr(app.state, "http_client", None)
    if client is None:
        return

    await client.aclose()
    app.state.http_client = None
    logger.info("Global HTTPX client shut down")
