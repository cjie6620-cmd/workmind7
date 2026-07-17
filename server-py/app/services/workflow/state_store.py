"""Redis-backed paused workflow state and resume locking."""

import asyncio
import json
import secrets
from datetime import datetime, timezone

from ...core.redis_client import get_redis


RUN_TTL_SECONDS = 24 * 60 * 60
LOCK_TTL_SECONDS = 5 * 60
_RUN_PREFIX = "workflow:run:"
_LOCK_PREFIX = "workflow:lock:"


def _run_key(thread_id: str) -> str:
    return f"{_RUN_PREFIX}{thread_id}"


def _lock_key(thread_id: str) -> str:
    return f"{_LOCK_PREFIX}{thread_id}"


async def save_workflow_run(thread_id: str, run: dict) -> dict:
    """保存可恢复快照并设置 TTL；Redis 失败必须让启动流程失败。"""
    snapshot = {
        **run,
        "threadId": thread_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps(snapshot, ensure_ascii=False)
    client = get_redis()
    await asyncio.to_thread(client.setex, _run_key(thread_id), RUN_TTL_SECONDS, payload)
    return snapshot


async def get_workflow_run(thread_id: str) -> dict | None:
    client = get_redis()
    raw = await asyncio.to_thread(client.get, _run_key(thread_id))
    if not raw:
        return None
    return json.loads(raw)


async def delete_workflow_run(thread_id: str) -> bool:
    client = get_redis()
    deleted = await asyncio.to_thread(client.delete, _run_key(thread_id))
    return bool(deleted)


async def acquire_workflow_lock(thread_id: str) -> str | None:
    """并发恢复仲裁：同一 thread 在一个时刻只能有一个执行者。"""
    token = secrets.token_urlsafe(24)
    client = get_redis()
    acquired = await asyncio.to_thread(
        client.set,
        _lock_key(thread_id),
        token,
        nx=True,
        ex=LOCK_TTL_SECONDS,
    )
    return token if acquired else None


async def release_workflow_lock(thread_id: str, token: str) -> None:
    """只释放自己持有的锁，避免过期后误删下一执行者的锁。"""
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """
    client = get_redis()
    await asyncio.to_thread(client.eval, script, 1, _lock_key(thread_id), token)
