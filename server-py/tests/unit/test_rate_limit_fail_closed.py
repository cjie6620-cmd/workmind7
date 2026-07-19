"""昂贵路径在 Redis 不可用时限流 fail-closed。"""

from app.middleware import STRICT_RATE_PATHS, _check_rate_limit


async def test_strict_path_denies_when_redis_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.redis_client.get_redis", boom)
    path = next(iter(STRICT_RATE_PATHS))
    assert await _check_rate_limit({"client": ("127.0.0.1", 0), "state": {}}, path) is False


async def test_strict_path_allows_fallback_under_testing(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setattr("app.core.redis_client.get_redis", boom)
    path = next(iter(STRICT_RATE_PATHS))
    assert await _check_rate_limit({"client": ("127.0.0.1", 0), "state": {}}, path) is True


async def test_non_strict_path_uses_fallback_bucket(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.core.redis_client.get_redis", boom)
    # 非昂贵路径仍允许进程内回退桶放行
    assert await _check_rate_limit({"client": ("127.0.0.1", 0), "state": {}}, "/api/chat/sessions") is True
