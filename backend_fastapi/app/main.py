"""FastAPI application factory and orchestration entrypoint."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from .bootstrap.lifecycle import (
    check_database_connection,
    initialize_celery,
    initialize_http_client,
    initialize_redis,
    shutdown_celery,
    shutdown_http_client,
    shutdown_redis,
)
from .bootstrap.exception_handlers import configure_exception_handlers
from .bootstrap.metrics import setup_metrics
from .bootstrap.middleware import configure_middleware
from .bootstrap.observability import init_sentry
from .bootstrap.providers import initialize_integration_vault, initialize_provider_state
from .bootstrap.routers import register_api_routes
from .core.celery_app import celery_app
from .core.settings import get_settings
from .core.test_mode import is_production
from .services import secret_vault
from .utils.alembic_check import AlembicSchemaStatus, capture_alembic_status
from .utils.crypto_utils import ensure_encrypted_env_loaded
from .utils.structured_logging import configure_logging

logger = structlog.get_logger("backend_fastapi.app")

_TRUTHY = {"1", "true", "yes", "on"}


def _expose_api_docs() -> bool:
    """Whether to mount /docs, /redoc and /openapi.json (F-82).

    Off in production unless an operator explicitly opts back in — the schema
    advertises the full admin route map, which is reconnaissance an anonymous
    caller has no reason to receive. Enforcement never depended on hiding it;
    this only stops publishing the map.
    """

    override = os.getenv("EXPOSE_API_DOCS")
    if override is not None and override.strip():
        return override.strip().lower() in _TRUTHY
    return not is_production()


def create_app() -> FastAPI:
    """Application factory used by ASGI servers and tests."""

    configure_logging()
    ensure_encrypted_env_loaded(log=logger)
    settings = get_settings()

    redis_url = (
        settings.redis_url or settings.celery_broker_url or celery_app.conf.broker_url
    )

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI):
        logger.info("app_startup_begin")
        db_ok = await check_database_connection()
        redis_client = await initialize_redis(lifespan_app, redis_url)
        celery_connection = await initialize_celery(lifespan_app)
        http_client = await initialize_http_client(lifespan_app)

        subsystem_status = {
            "database": db_ok,
            "redis": redis_client is not None,
            "celery": celery_connection is not None,
            "http_client": http_client is not None,
            "ocr": feature_flags["ocr"],
            "translation": feature_flags["translation"],
        }
        lifespan_app.state.subsystems = subsystem_status

        async def _vault_refresher() -> None:
            # Picks up vault edits made through another worker process.
            while True:
                await asyncio.sleep(secret_vault.REFRESH_INTERVAL_SECONDS)
                await asyncio.to_thread(secret_vault.refresh_if_stale)

        vault_task = asyncio.create_task(_vault_refresher())
        logger.info("Subsystem availability", subsystems=subsystem_status)

        if getattr(settings, "alembic_check_on_startup", False):
            logger.info(
                "Running Alembic schema status check (ALEMBIC_CHECK_ON_STARTUP enabled)"
            )
            loop = asyncio.get_running_loop()
            status: AlembicSchemaStatus = await loop.run_in_executor(
                None, capture_alembic_status
            )
            lifespan_app.state.alembic_status = status
            if status.config_missing:
                logger.info(
                    "Alembic configuration unavailable; skipping schema drift detection"
                )
            else:
                for error in status.errors:
                    logger.warning("Alembic command issue", error=error)
                if status.schema_drift:
                    logger.error(
                        "Schema drift detected – pending manual resolution",
                        current=sorted(status.current_revisions or ()),
                        heads=sorted(status.head_revisions or ()),
                    )
                elif not status.determinate:
                    # Not the same thing as "no drift": the check could not be
                    # evaluated, so it must not report success.
                    logger.warning(
                        "Alembic schema check inconclusive; drift NOT verified",
                        current=(
                            sorted(status.current_revisions)
                            if status.current_revisions is not None
                            else None
                        ),
                        heads=(
                            sorted(status.head_revisions)
                            if status.head_revisions is not None
                            else None
                        ),
                    )
                else:
                    logger.info(
                        "Alembic schema check passed",
                        current=sorted(status.current_revisions or ()),
                        heads=sorted(status.head_revisions or ()),
                    )
        try:
            yield
        finally:
            logger.info("app_shutdown_begin")
            vault_task.cancel()
            await shutdown_http_client(lifespan_app)
            await shutdown_celery(lifespan_app)
            await shutdown_redis(lifespan_app)
            logger.info("app_shutdown_complete")

    # F-82: the interactive docs enumerate every route, including 69 admin
    # paths, to anonymous callers. They are a development convenience, so they
    # are served outside production and switched off entirely in production
    # (set EXPOSE_API_DOCS=true to override for a private/staging deploy).
    expose_docs = _expose_api_docs()
    app = FastAPI(
        title="Manga Website API",
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.state.settings = settings
    app.state.celery = celery_app
    app.state.alembic_status: AlembicSchemaStatus | None = None

    initialize_integration_vault(app)
    # Admin-panel overrides for allow-listed .env keys. Applied before Sentry
    # and the providers read their settings; a missing table (before the
    # migration runs) or an unreachable DB just leaves .env in charge.
    secret_vault.refresh_if_stale()
    feature_flags = initialize_provider_state(app, settings)
    app.state.features = feature_flags

    init_sentry(settings)
    allowed_origins = configure_middleware(app, settings)

    setup_metrics(app)

    configure_exception_handlers(app)

    # Register these infra endpoints on the bare app router *before*
    # register_api_routes mounts the (auth-gated) health_router at "" for
    # backward compatibility. Starlette matches routes in registration
    # order, so defining "/health" first is what makes this public liveness
    # probe win over the admin-only detailed view living at /api/health and
    # /api/v1/health.
    @app.get("/", include_in_schema=False)
    def root() -> dict[str, object]:
        """Return basic service metadata for quick smoke tests."""

        subsystems = getattr(app.state, "subsystems", {})
        features = getattr(app.state, "features", feature_flags)

        return {
            "service": "manga-stack-backend",
            "status": "ok",
            "docs_url": app.docs_url,
            "redoc_url": app.redoc_url,
            "openapi_url": app.openapi_url,
            "features": features,
            "subsystems": subsystems,
        }

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Public, unauthenticated liveness probe.

        Deliberately minimal — no DB credentials, connection strings, or
        internal topology. The detailed, auth-gated diagnostics view lives
        at /api/health (see api/routers/health.py).
        """

        db_ok = await check_database_connection()
        return {
            "status": "ok" if db_ok else "degraded",
            "service": "backend",
            "db": "ok" if db_ok else "error",
        }

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        """Simple health check endpoint."""

        return {"ok": True}

    register_api_routes(app)

    logger.info(
        "Runtime configuration",
        origins=allowed_origins,
        frontend_url=settings.frontend_url,
        api_mounts=["/", "/api"],
    )
    logger.info("Feature availability", features=feature_flags)

    return app


app = create_app()
