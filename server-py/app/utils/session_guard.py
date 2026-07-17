"""

会话归属校验



防止 IDOR：用户只能访问自己的 session。

"""

from fastapi import HTTPException

from sqlalchemy import select


from ..core.database import async_session_factory

from ..models.entities import Conversation


# 带 user_id 前缀的会话 ID 格式：{prefix}{user_id}_{suffix}

_OWNED_SESSION_PREFIXES = ("session_", "agent_", "knowledge_")


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """校验 sessionId 是否包含当前用户前缀（新会话尚无 DB 记录时使用）"""

    for prefix in _OWNED_SESSION_PREFIXES:
        if session_id.startswith(f"{prefix}{user_id}_"):
            return True

    return False


def normalize_chat_session_id(session_id: str, user_id: str) -> str:
    """将 legacy default 会话替换为用户专属 ID"""

    if not session_id or session_id == "default":
        import time

        return f"session_{user_id}_{int(time.time() * 1000)}"

    return session_id


async def get_session_owner(session_id: str) -> str | None:
    """获取会话所属 user_id（取首条消息的 user_id）"""

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
    """校验会话归属，非本人则 403"""

    if not session_id or session_id == "default":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "无效的会话 ID"}},
        )

    owner = await get_session_owner(session_id)

    if owner is not None:
        if owner != user_id:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "FORBIDDEN", "message": "无权访问该会话"}},
            )

        return

    if session_belongs_to_user(session_id, user_id):
        return

    raise HTTPException(
        status_code=403,
        detail={"error": {"code": "FORBIDDEN", "message": "无权访问该会话"}},
    )
