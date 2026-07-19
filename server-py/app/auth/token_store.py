"""Refresh token jti 存储：一次性轮换 + 登出吊销（Redis 实现）。

设计：
- 签发 refresh token 时登记其 jti（`auth:refresh:jti:{jti}` → user_id，TTL=refresh 有效期）。
- 刷新时原子「校验归属 + 删除」jti，实现一次性使用；旧 jti 立即失效，重放被拒。
- 登出时删除该 jti，使其对应的 refresh token 立即作废。

同步 redis-py 调用统一走线程池，避免阻塞事件循环。
"""

import asyncio

from ..core.redis_client import get_redis

_JTI_PREFIX = "auth:refresh:jti:"

# 校验归属并原子删除，保证并发刷新只有一个能成功
_CONSUME_SCRIPT = """
local owner = redis.call('GET', KEYS[1])
if owner == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1
end
return 0
"""


def _jti_key(jti: str) -> str:
    return f"{_JTI_PREFIX}{jti}"


async def register_refresh_jti(jti: str, user_id: str, ttl_seconds: int) -> None:
    """签发 refresh token 时登记 jti，作为后续刷新的有效凭据。"""
    client = get_redis()
    await asyncio.to_thread(client.set, _jti_key(jti), user_id, ex=max(1, ttl_seconds))


async def consume_refresh_jti(jti: str, user_id: str) -> bool:
    """一次性消费 jti：存在且归属匹配才返回 True，并原子删除防止重放。"""
    if not jti:
        return False
    client = get_redis()
    result = await asyncio.to_thread(client.eval, _CONSUME_SCRIPT, 1, _jti_key(jti), str(user_id))
    return int(result) == 1


async def revoke_refresh_jti(jti: str) -> None:
    """登出时吊销指定 refresh jti（幂等）。"""
    if not jti:
        return
    client = get_redis()
    await asyncio.to_thread(client.delete, _jti_key(jti))
