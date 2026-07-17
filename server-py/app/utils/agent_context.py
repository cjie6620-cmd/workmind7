"""Agent 执行上下文（当前用户 ID，供工具层读取）"""

from contextlib import asynccontextmanager

from contextvars import ContextVar


_agent_user_id: ContextVar[str | None] = ContextVar("agent_user_id", default=None)


def get_agent_user_id() -> str | None:
    """获取当前 Agent 任务所属用户 ID"""

    return _agent_user_id.get()


@asynccontextmanager
async def agent_user_scope(user_id: str):
    """在 Agent 任务执行期间绑定 user_id"""

    token = _agent_user_id.set(user_id)

    try:
        yield

    finally:
        _agent_user_id.reset(token)
