"""Global platform-default usage ceiling (SRS 2E.3).

A per-account limit (2E.1) bounds what one reader can consume; this bounds
what the platform's OWN default providers hand out in total, across every
account not using their own key, per day. Redis-backed (same pattern as
``daily_limiter``/``circuit_breaker``): fails open if Redis is unavailable
rather than blocking processing on an infra hiccup, and the administrator
is alerted once the ceiling is approached (1I.3.2), not only once it's hit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import SystemSettings

# 1I.3.2: alert once the ceiling is this close, not only once it's blown
# through -- gives the administrator time to react.
ALERT_THRESHOLD_RATIO = 0.8


def _redis(request: Request) -> Optional[Redis]:
    client = getattr(request.app.state, "redis", None)
    return client if isinstance(client, Redis) else None


def _ceiling(db: Session) -> Optional[int]:
    settings = db.query(SystemSettings).first()
    value = (
        getattr(settings, "platform_default_daily_ceiling", None) if settings else None
    )
    return int(value) if value else None


async def check_and_increment(request: Request, db: Session, service: str) -> None:
    """Increment today's platform-default usage counter for ``service`` and
    raise if that would exceed the administrator's configured ceiling
    (2E.3). A no-op when no ceiling is configured or Redis is unavailable."""

    ceiling = _ceiling(db)
    if not ceiling:
        return

    redis_client = _redis(request)
    if not redis_client:
        return

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"platform_usage:{service}:{date_str}"
    alert_key = f"platform_usage_alerted:{service}:{date_str}"

    try:
        async with redis_client.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, 86400, nx=True)
            count, _ = await pipe.execute()
    except Exception:
        return  # fail open

    current = int(count)

    if current >= ceiling:
        from .notification_service import notify_async

        notify_async(
            type="platform_ceiling.exceeded",
            title=f"Platform default {service} ceiling reached",
            body=(
                f"The platform-default {service} provider has served "
                f"{current} of its {ceiling}/day ceiling. New default-"
                "provider requests are paused until it resets."
            ),
            category="administrative",
            priority="high",
            target_type="platform_ceiling",
            target_id=service,
            dedup_key=f"platform_ceiling.exceeded:{service}:{date_str}",
        )
        raise ApiError(
            ErrorCode.QUOTA_EXCEEDED,
            (
                "The platform's default provider has reached its daily "
                "capacity. Add your own API key in Settings to keep "
                "processing, or try again after it resets."
            ),
            details={"service": service, "ceiling": ceiling},
        )

    if current >= ceiling * ALERT_THRESHOLD_RATIO:
        try:
            already_alerted = await redis_client.get(alert_key)
        except Exception:
            already_alerted = None
        if not already_alerted:
            from .notification_service import notify_async

            notify_async(
                type="platform_ceiling.approaching",
                title=f"Platform default {service} usage approaching its ceiling",
                body=(
                    f"The platform-default {service} provider has served "
                    f"{current} of its {ceiling}/day ceiling."
                ),
                category="administrative",
                priority="normal",
                target_type="platform_ceiling",
                target_id=service,
                dedup_key=f"platform_ceiling.approaching:{service}:{date_str}",
            )
            try:
                await redis_client.set(alert_key, "1", ex=86400)
            except Exception:
                pass


__all__ = ["check_and_increment", "ALERT_THRESHOLD_RATIO"]
