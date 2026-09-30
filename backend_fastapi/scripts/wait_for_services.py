#!/usr/bin/env python3
"""Block until core infrastructure services accept connections."""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

import psycopg2
from redis import Redis


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2"):
        return "postgresql" + url[len("postgresql+psycopg2") :]
    if url.startswith("postgresql+psycopg"):
        return "postgresql" + url[len("postgresql+psycop") :]
    return url


def _wait_for_postgres(
    url: Optional[str], attempts: int, base_delay: float, max_delay: float
) -> None:
    if not url:
        print("[wait_for_services] DATABASE_URL not provided; skipping Postgres wait")
        return

    normalized = _normalize_database_url(url)
    for attempt in range(1, attempts + 1):
        try:
            with psycopg2.connect(normalized) as connection:
                connection.cursor().execute("SELECT 1")
            print("[wait_for_services] PostgreSQL connection established")
            return
        except Exception as exc:  # pragma: no cover - depends on runtime availability
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            print(
                f"[wait_for_services] PostgreSQL unavailable (attempt {attempt}/{attempts}): {exc}. "
                f"Retrying in {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)

    raise RuntimeError("PostgreSQL never became available within the allotted attempts")


def _compose_redis_url() -> Optional[str]:
    direct_url = (
        os.environ.get("REDIS_URL")
        or os.environ.get("CELERY_BROKER_URL")
        or os.environ.get("CELERY_RESULT_BACKEND")
    )
    if direct_url:
        return direct_url

    password = os.environ.get("REDIS_PASSWORD")
    if not password:
        return None

    username = os.environ.get("REDIS_USERNAME", "")
    host = os.environ.get("REDIS_HOST", "redis")
    port = os.environ.get("REDIS_PORT", "6379")
    db = os.environ.get("REDIS_DB", "0")
    if username:
        return f"redis://{username}:{password}@{host}:{port}/{db}"
    return f"redis://:{password}@{host}:{port}/{db}"


def _wait_for_redis(
    url: Optional[str], attempts: int, base_delay: float, max_delay: float
) -> None:
    if not url:
        print("[wait_for_services] REDIS_URL not provided; skipping Redis wait")
        return

    for attempt in range(1, attempts + 1):
        try:
            client = Redis.from_url(url)
            client.ping()
            client.close()
            print("[wait_for_services] Redis connection established")
            return
        except Exception as exc:  # pragma: no cover - depends on runtime availability
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            print(
                f"[wait_for_services] Redis unavailable (attempt {attempt}/{attempts}): {exc}. "
                f"Retrying in {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)

    raise RuntimeError("Redis never became available within the allotted attempts")


def main() -> int:
    attempts = _env_int("SERVICE_WAIT_ATTEMPTS", 30)
    base_delay = _env_float("SERVICE_WAIT_BASE_DELAY", 1.5)
    max_delay = _env_float("SERVICE_WAIT_MAX_DELAY", 10.0)

    database_url = os.environ.get("DATABASE_URL")
    redis_url = _compose_redis_url()

    try:
        _wait_for_postgres(database_url, attempts, base_delay, max_delay)
        _wait_for_redis(redis_url, attempts, base_delay, max_delay)
    except Exception as exc:  # pragma: no cover - depends on runtime availability
        print(f"[wait_for_services] Fatal: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
