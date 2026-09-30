"""Tests for explicit manga cache invalidation on write (item 34)."""

from __future__ import annotations

from backend_fastapi.app.utils import cache_invalidation


class _FakeRedis:
    def __init__(self, keys):
        self.store = {k: "v" for k in keys}

    def scan_iter(self, match="*", count=100):
        prefix = match.rstrip("*")
        # snapshot to allow deletion during iteration
        for key in list(self.store):
            if key.startswith(prefix):
                yield key

    def delete(self, key):
        self.store.pop(key, None)


def test_invalidate_manga_list_cache_removes_only_list_keys():
    redis = _FakeRedis(
        ["manga_list:a", "manga_list:b", "manga:1", "manga_chapters:1:asc"]
    )
    removed = cache_invalidation.invalidate_manga_list_cache(redis)
    assert removed == 2
    assert set(redis.store) == {"manga:1", "manga_chapters:1:asc"}


def test_invalidate_manga_detail_cache_for_specific_id():
    redis = _FakeRedis(["manga:1", "manga:12", "manga_chapters:1:asc", "manga:2"])
    removed = cache_invalidation.invalidate_manga_detail_cache(redis, manga_id=1)
    # matches manga:1, manga:12 (prefix), manga_chapters:1:asc
    assert "manga:2" in redis.store
    assert removed >= 2


def test_invalidate_all_manga_caches():
    redis = _FakeRedis(["manga_list:a", "manga:1", "manga_chapters:1:asc"])
    removed = cache_invalidation.invalidate_all_manga_caches(redis)
    assert removed == 3
    assert redis.store == {}


def test_invalidation_is_noop_without_redis():
    assert cache_invalidation.invalidate_all_manga_caches(None) == 0
