"""
健康检查路由模块

- /live: 存活检查（不查依赖）
- /ready: 就绪检查（DB + Redis）
- /stream: 长连接心跳 SSE（运维/验收探活，不调 LLM）
- /: 详细健康（仅开发环境）
"""

import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..config import config
from ..services.cache import cache
from ..utils.responses import error_response

health_router = APIRouter()
_start_time = time.monotonic()
_is_production = config["app"]["env"] == "production"


def _uptime_seconds() -> int:
    """使用单调时钟，避免系统校时导致运行时长倒退或跳变。"""
    return int(time.monotonic() - _start_time)


@health_router.get("/live")
async def health_live():
    """存活检查：进程存活，不查依赖"""
    return {"status": "ok", "uptime": _uptime_seconds()}


@health_router.get("/stream")
async def health_stream():
    """长连接心跳 SSE：用于代理超时与多 worker 长稳验收（T2-09）。"""

    async def event_generator():
        seq = 0
        while True:
            seq += 1
            payload = {"seq": seq, "uptime": _uptime_seconds(), "status": "ok"}
            yield {"event": "ping", "data": json.dumps(payload, ensure_ascii=False)}
            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())


@health_router.get("/ready")
async def health_ready():
    """就绪检查：DB + Redis 均可用时 200，否则 503"""
    from sqlalchemy import text

    from ..core.database import async_session_factory
    from ..core.redis_client import get_redis

    errors = []

    try:
        from ..core.database import check_tables_status

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        table_status = await check_tables_status()
        if table_status.get("status") != "ready":
            errors.append(f"database schema: {table_status.get('message', 'not ready')}")
    except Exception as e:
        errors.append(f"database: {e}")

    try:
        redis_client = get_redis()
        if not await asyncio.to_thread(redis_client.ping):
            errors.append("redis: ping failed")
    except Exception as e:
        errors.append(f"redis: {e}")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "errors": errors},
        )

    return {"status": "ready", "uptime": _uptime_seconds()}


@health_router.get("")
async def health_root():
    """详细健康检查（生产环境返回 404）"""
    if _is_production:
        return error_response(404, "Not found")

    from ..core.database import check_tables_status

    try:
        db_status = await check_tables_status()
    except Exception as e:
        db_status = {"status": "error", "message": str(e)}

    return {
        "status": "healthy",
        "uptime": _uptime_seconds(),
        "cache": await asyncio.to_thread(cache.get_stats),
        "version": "1.0.0",
        "database": db_status,
    }
