"""Agent 执行上下文：把当前用户 ID 绑定到异步任务链

LangGraph 工具函数（read_doc / write_report 等）不在 FastAPI 依赖注入链上，
拿不到 UserContext；用 ContextVar 传递 user_id，天然按 asyncio Task 隔离，
并发运行的多个 Agent 任务互不串扰。工具层取不到 user_id 时必须 fail-closed。
"""

from contextlib import asynccontextmanager
from contextvars import ContextVar

_agent_user_id: ContextVar[str | None] = ContextVar("agent_user_id", default=None)


def get_agent_user_id() -> str | None:
    """获取当前 Agent 任务所属用户 ID；未在 agent_user_scope 内调用时返回 None"""
    return _agent_user_id.get()


@asynccontextmanager
async def agent_user_scope(user_id: str):
    """在 Agent 任务执行期间绑定 user_id，退出时恢复原值（支持嵌套）"""
    token = _agent_user_id.set(user_id)
    try:
        yield
    finally:
        _agent_user_id.reset(token)
