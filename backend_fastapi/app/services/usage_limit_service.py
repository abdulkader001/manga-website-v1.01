"""Server-side page/word usage-limit enforcement (SRS 2E).

The platform never limits by cost (2E.1A) -- a user limits by volume: how
many manga pages (or words) they're willing to have processed in a window
they choose (day/week/month, 1E.1.3). Two independent counters exist per
account (2E.2): ``usage_current`` for OCR+translation ("processing") and
``ai_usage_current`` for AI-assisted work, both measured in the same
configured unit and reset on the same window.

Enforcement is server-side even for user-owned keys (2E.2), cache hits are
always free (2E.2/2F.1), and reading is never blocked -- only processing
pauses (2E.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models.processing_settings import UserProcessingSettings
from . import processing_settings_service

Kind = Literal["translation", "ai"]

_UNIT_LABEL = {"pages": "pages", "words": "words"}


def _period_end(period_start: datetime, window: str) -> datetime:
    if window == "day":
        return period_start + timedelta(days=1)
    if window == "week":
        return period_start + timedelta(days=7)
    # month: add a calendar month, clamping the day (mirrors the client's
    # existing nextReset() in frontend/src/utils/translationUsage.ts so
    # server and client agree on when a period rolls over).
    year = period_start.year + (1 if period_start.month == 12 else 0)
    month = 1 if period_start.month == 12 else period_start.month + 1
    if month == 12:
        next_month_days = 31
    else:
        next_next = (
            datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)
        )
        next_month_days = (next_next - datetime(year, month, 1)).days
    day = min(period_start.day, next_month_days)
    return period_start.replace(year=year, month=month, day=day)


def _format_reset_time(delta: timedelta) -> str:
    total_seconds = max(1, int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{max(1, minutes)}m"


@dataclass
class UsageSnapshot:
    unit: str
    window: str
    limit_value: Optional[int]
    usage_current: int
    ai_usage_current: int
    period_start: datetime
    period_end: datetime
    rolled_over: bool


def _rollover_if_needed(record: UserProcessingSettings, now: datetime) -> bool:
    """Return True and zero both counters if the current period has elapsed."""

    end = _period_end(record.usage_period_start, record.usage_limit_window)
    if now < end:
        return False
    record.usage_current = 0
    record.ai_usage_current = 0
    record.usage_period_start = now
    return True


def snapshot(
    db: Session, user_id: int, *, persist_rollover: bool = False
) -> UsageSnapshot:
    """A read-only view of the account's current usage period.

    When ``persist_rollover`` is False (the default, used by GET-style
    reads) an elapsed period is reflected in the returned snapshot without
    writing to the database -- only ``check_and_consume`` actually rolls
    the period over and commits.
    """

    record = processing_settings_service.get_or_create(db, user_id)
    now = datetime.utcnow()
    end = _period_end(record.usage_period_start, record.usage_limit_window)
    if now >= end:
        if persist_rollover:
            _rollover_if_needed(record, now)
            db.commit()
            db.refresh(record)
            end = _period_end(record.usage_period_start, record.usage_limit_window)
        return UsageSnapshot(
            unit=record.usage_limit_unit,
            window=record.usage_limit_window,
            limit_value=record.usage_limit_value,
            usage_current=0 if not persist_rollover else record.usage_current,
            ai_usage_current=0 if not persist_rollover else record.ai_usage_current,
            period_start=record.usage_period_start if persist_rollover else now,
            period_end=end
            if persist_rollover
            else _period_end(now, record.usage_limit_window),
            rolled_over=True,
        )
    return UsageSnapshot(
        unit=record.usage_limit_unit,
        window=record.usage_limit_window,
        limit_value=record.usage_limit_value,
        usage_current=record.usage_current,
        ai_usage_current=record.ai_usage_current,
        period_start=record.usage_period_start,
        period_end=end,
        rolled_over=False,
    )


def check_and_consume(db: Session, user_id: int, kind: Kind, amount: int) -> None:
    """Enforce and record ``amount`` units of processing against the account.

    Cache hits must never call this (2E.2/2F.1) -- only work that actually
    produces something new consumes quota. Raises ``ApiError`` (rendered by
    the global handler, 1H.8.2 wording) when the account's configured limit
    would be exceeded; a caller with no limit configured (``limit_value`` is
    None) is unbounded here, subject only to platform-wide ceilings (2E.3).
    """

    if amount <= 0:
        return

    record = processing_settings_service.get_or_create(db, user_id)
    now = datetime.utcnow()
    _rollover_if_needed(record, now)

    if record.usage_limit_value:
        current = (
            record.usage_current if kind == "translation" else record.ai_usage_current
        )
        if current + amount > record.usage_limit_value:
            end = _period_end(record.usage_period_start, record.usage_limit_window)
            retry_after = max(1, int((end - now).total_seconds()))
            unit_label = _UNIT_LABEL.get(
                record.usage_limit_unit, record.usage_limit_unit
            )
            label = "AI" if kind == "ai" else "processing"
            db.commit()  # persist any rollover that already happened
            raise ApiError(
                ErrorCode.QUOTA_EXCEEDED,
                (
                    f"You've reached your {label} limit for this period "
                    f"({record.usage_limit_value} {unit_label}). It resets in "
                    f"{_format_reset_time(end - now)}, or you can raise it in "
                    "Settings."
                ),
                details={
                    "retry_after_seconds": retry_after,
                    "limit": record.usage_limit_value,
                    "unit": record.usage_limit_unit,
                    "kind": kind,
                },
            )

    if kind == "ai":
        record.ai_usage_current += amount
    else:
        record.usage_current += amount
    db.commit()


__all__ = ["UsageSnapshot", "snapshot", "check_and_consume"]
