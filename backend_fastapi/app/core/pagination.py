"""Standard pagination contract (SRS 1B.4.5).

Every collection endpoint accepts ``page`` and ``per_page`` (default 50, maximum
200) and returns the ``meta`` block from 1B.4.2. No endpoint may return an
unbounded collection — ``per_page`` is always bounded by ``MAX_PER_PAGE``.

Endpoints built on the versioned envelope surface should depend on
``PageParams`` and wrap their results with ``paginated_envelope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Query

from .api_errors import pagination_meta, success_body

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

# F-75: ``page`` was bounded below (ge=1) but not above, so ``page=<huge>``
# produced an OFFSET that overflows PostgreSQL's bigint and returned an
# unauthenticated 500 (SQLite silently coped, which is why no test caught it).
# 100_000 pages is far past any real result set while keeping
# ``(page - 1) * per_page`` comfortably inside int64.
MAX_PAGE = 100_000

# Same reasoning for the endpoints that take a raw ``offset`` instead of a
# page number (comments, moderation reports, notifications).
MAX_OFFSET = MAX_PAGE * MAX_PER_PAGE


@dataclass(frozen=True)
class PageParams:
    """Validated pagination parameters (SRS 1B.4.5).

    Use as a FastAPI dependency::

        def list_things(page: PageParams = Depends()): ...
    """

    page: int = Query(
        1, ge=1, le=MAX_PAGE, description="1-indexed page number"
    )
    per_page: int = Query(
        DEFAULT_PER_PAGE,
        ge=1,
        le=MAX_PER_PAGE,
        description=f"Items per page (max {MAX_PER_PAGE})",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        return self.per_page


def paginated_envelope(
    items: Any, *, page: int, per_page: int, total: int
) -> dict[str, Any]:
    """Wrap a page of results in the standard success envelope with meta."""

    return success_body(items, meta=pagination_meta(page, per_page, total))
