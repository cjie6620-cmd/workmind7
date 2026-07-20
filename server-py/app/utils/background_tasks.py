"""后台业务任务的优雅停机等待

agent / erp / workflow 三类路由都持有「已受理、与连接解耦」的后台任务集合，
停机时共用同一策略：先给完成窗口（保存结果/落终态），超时再取消并等待回收。
"""

import asyncio
from collections.abc import Iterable


async def wait_or_cancel_tasks(tasks: Iterable[asyncio.Task], timeout_seconds: float) -> None:
    """等待在途任务最多 timeout_seconds 秒，仍未完成的取消并等待其退出。"""
    pending = [task for task in tasks if not task.done()]
    if not pending:
        return
    _, still_pending = await asyncio.wait(pending, timeout=timeout_seconds)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
