"""会话归属校验（防 IDOR）

会话 ID 约定为 {prefix}{user_id}_{suffix}（prefix ∈ session_/agent_/knowledge_）。
校验顺序：数据库首条消息的 user_id 是权威归属；会话尚未落库（新会话）时，
退化为校验 ID 前缀是否携带当前用户 ID。两者都不满足一律 403。
"""

from fastapi import HTTPException
from sqlalchemy import select

from ..core.database import async_session_factory
from ..models.entities import Conversation

# 带 user_id 前缀的会话 ID 格式：{prefix}{user_id}_{suffix}
_OWNED_SESSION_PREFIXES = ("session_", "agent_", "knowledge_")


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """校验 sessionId 是否携带当前用户前缀（新会话尚无 DB 记录时的唯一依据）"""
    return any(session_id.startswith(f"{prefix}{user_id}_") for prefix in _OWNED_SESSION_PREFIXES)


def normalize_chat_session_id(session_id: str, user_id: str) -> str:
    """把空值或 legacy 的 "default" 会话 ID 替换为用户专属 ID，其余原样返回"""
    if not session_id or session_id == "default":
        import time

        return f"session_{user_id}_{int(time.time() * 1000)}"
    return session_id


async def get_session_owner(session_id: str) -> str | None:
    """取会话首条带 user_id 的消息作为权威归属；会话未落库时返回 None"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Conversation.user_id)
            .where(Conversation.session_id == session_id)
            .where(Conversation.user_id.isnot(None))
            .order_by(Conversation.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def assert_session_owner(session_id: str, user_id: str) -> None:
    """校验会话归属，非本人抛 403；供所有按 session_id 读写的路由复用"""
    # 第一步：拒绝无差别共享的 ID（空 / default），它们无法建立归属
    if not session_id or session_id == "default":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "无效的会话 ID"}},
        )

    # 第二步：数据库中已有消息时，以首条消息的 user_id 为准
    owner = await get_session_owner(session_id)
    if owner is not None:
        if owner != user_id:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "FORBIDDEN", "message": "无权访问该会话"}},
            )
        return

    # 第三步：新会话尚未落库，只接受携带本人前缀的 ID
    if session_belongs_to_user(session_id, user_id):
        return

    raise HTTPException(
        status_code=403,
        detail={"error": {"code": "FORBIDDEN", "message": "无权访问该会话"}},
    )
