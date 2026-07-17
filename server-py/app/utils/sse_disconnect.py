"""SSE 客户端断开检测与后台任务取消"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from .logger import logger


async def pump_queue_events(
    request: Request,
    queue: asyncio.Queue,
    done_event: asyncio.Event,
    *,
    task: asyncio.Task | None = None,
) -> AsyncIterator[Any]:
    """
    从队列泵送 SSE 事件；客户端断开时取消后台 task。

    用于 workflow / erp / prompt 等「后台 task + 队列」模式。
    """
    try:
        while not done_event.is_set() or not queue.empty():
            if await request.is_disconnected():
                logger.info("sse client disconnected")
                if task and not task.done():
                    task.cancel()
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except asyncio.TimeoutError:
                continue
    finally:
        await cancel_task(task)


async def cancel_task(task: asyncio.Task | None) -> None:
    """取消并等待后台任务结束"""
    if not task or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def client_still_connected(request: Request) -> bool:
    """客户端仍连接时返回 True"""
    return not await request.is_disconnected()
