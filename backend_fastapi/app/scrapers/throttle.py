"""Per-site AutoThrottle, the way Scrapy does it.

A site that answers slowly is busy; a site that answers 429/503/403 is
pushing back. Reading at a fixed pace ignores both, and that is what gets a
server blocked. Here each site gets its own delay:

* after each answer the delay moves halfway towards the time the site took
  to answer (``latency / TARGET_CONCURRENCY``), so a slow site is read
  slowly and a fast one a little faster, never under the scraper's own
  minimum;
* a 429/503/403 doubles it (at least ``BLOCK_FLOOR`` seconds);
* it never exceeds ``MAX_DELAY``.

The state lives in the worker process, like Scrapy's; each worker learns
each site's pace on its own.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

TARGET_CONCURRENCY = 1.0
MAX_DELAY = 30.0
BLOCK_FLOOR = 5.0
PUSHBACK_STATUSES = {403, 429, 503}

_delays: Dict[str, float] = {}
_lock = threading.Lock()


def delay_for(domain: str, minimum: float = 0.0) -> float:
    """Seconds to wait before the next request to ``domain``."""

    with _lock:
        return max(float(minimum), _delays.get(domain, 0.0))


def record(domain: str, latency: float, status: Optional[int] = None) -> float:
    """Learn from one answer; returns the new delay."""

    status = status if isinstance(status, int) else None
    with _lock:
        current = _delays.get(domain, 0.0)
        if status in PUSHBACK_STATUSES:
            new = max(BLOCK_FLOOR, current * 2)
        else:
            target = max(0.0, float(latency)) / TARGET_CONCURRENCY
            # Scrapy: never drop faster than halfway in one step, and never
            # speed up on an error answer.
            new = (current + target) / 2.0
            if status is not None and status >= 400:
                new = max(new, current)
        new = min(MAX_DELAY, new)
        _delays[domain] = new
        return new


def reset(domain: Optional[str] = None) -> None:
    with _lock:
        if domain is None:
            _delays.clear()
        else:
            _delays.pop(domain, None)
