from typing import Optional
from fastapi import Request
from redis.asyncio import Redis

from datetime import datetime, timezone

from ..core.api_errors import ApiError, ErrorCode

# Service key -> the noun used in the 1H.8.2 quota message ("translation
# limit", "OCR limit").
_SERVICE_LABELS = {
    "translation": "translation",
    "ocr": "OCR",
}


def _format_reset_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{max(1, minutes)}m"


class DailyUserLimiter:
    def _redis(self, request: Request) -> Optional[Redis]:
        client = getattr(request.app.state, "redis", None)
        return client if isinstance(client, Redis) else None

    async def check_limit(
        self, request: Request, service: str, user_id: int, limit: int = 10
    ):
        from ..core.test_mode import test_mode_active

        if test_mode_active():
            return

        redis_client = self._redis(request)
        if not redis_client:
            return

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        key = f"usage:{service}:{user_id}:{date_str}"

        try:
            async with redis_client.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, 86400, nx=True)  # 24h TTL
                count, _ = await pipe.execute()
        except Exception:
            return  # Fail open if redis is broken

        current = int(count)
        if current > limit:
            # Calculate seconds until midnight UTC
            tomorrow = datetime(
                now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc
            )
            retry_after = max(1, int((tomorrow - now).total_seconds()))

            # SRS 1H.8.2 exact user-facing message: "You've reached your
            # translation limit for this period. It resets in [time], or you
            # can raise it in Settings."
            label = _SERVICE_LABELS.get(service, service)

            from ..services.notification_service import notify_async

            notify_async(
                type="quota.exceeded",
                title=f"Your {label} limit is reached",
                body=(
                    f"You've reached your {label} limit for this period. It "
                    f"resets in {_format_reset_time(retry_after)}."
                ),
                user_id=user_id,
                data={"service": service, "limit": limit},
                target_type="quota",
                target_id=service,
                dedup_key=f"quota.exceeded:{service}",
            )

            raise ApiError(
                ErrorCode.QUOTA_EXCEEDED,
                (
                    f"You've reached your {label} limit for this period. "
                    f"It resets in {_format_reset_time(retry_after)}, or you "
                    "can raise it in Settings."
                ),
                details={"retry_after_seconds": retry_after, "limit": limit},
            )


daily_user_limiter = DailyUserLimiter()
