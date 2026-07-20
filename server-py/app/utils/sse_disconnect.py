"""SSE 客户端断连检测与队列泵送

配合「受理即返回 + 后台 task + asyncio.Queue」模式使用：
业务任务只往队列写事件，本模块负责把事件泵送给客户端并感知断连。
断连语义全站统一：已受理的业务命令（agent/erp/workflow/prompt A-B）
断连仅停止推送，任务继续执行并落终态，绝不随连接取消。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from .logger import logger


async def pump_queue_events(
    request: Request,
    queue: asyncio.Queue,
    done_event: asyncio.Event,
) -> AsyncIterator[Any]:
    """从队列泵送 SSE 事件，直到任务完成且队列排空，或客户端断连。

    断连只中断推送循环，后台任务继续运行（业务取消必须走显式取消接口）。
    0.5s 的 wait_for 超时兼顾两件事：既能及时发现断连，又避免空转烧 CPU。
    """
    while not done_event.is_set() or not queue.empty():
        if await request.is_disconnected():
            logger.info("sse client disconnected")
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.5)
            yield item
        except asyncio.TimeoutError:
            continue


async def client_still_connected(request: Request) -> bool:
    """客户端仍连接时返回 True（流式生成中逐段检查用）"""
    return not await request.is_disconnected()
