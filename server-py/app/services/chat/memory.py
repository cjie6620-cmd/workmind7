"""
会话记忆管理模块

提供两大功能：
1. 短期记忆（会话历史）：存储在 PostgreSQL
2. 用户画像（跨会话）：存储在 PostgreSQL

特点：
- 异步操作，基于 asyncpg
- 自动裁剪避免超出 token 限制
"""

from pydantic import BaseModel
from typing import Optional, List, Literal

from ..model import get_chat_model
from ...core.database import async_session_factory
from ...models.entities import Conversation
from ...utils.logger import logger
from ...utils.llm_parse import parse_with_retry


# ── Token 估算 ──────────────────────────────────────────────


def est_tokens(text=""):
    """
    估算文本 token 数量

    中文约 0.6 tokens/字符，英文约 0.25 tokens/字符
    """
    cn = sum(1 for c in text if "一" <= c <= "鿿")
    return int(cn * 0.6 + (len(text) - cn) * 0.25)


# ── 会话历史管理（PostgreSQL）───────────────────────────────


async def get_history_db(session_id: str, limit: int | None = None) -> List[dict]:
    """
    获取指定会话的历史消息（从 PostgreSQL）

    返回消息列表，按时间升序。limit 传入时只取最近 limit 条（再按时间升序返回），
    用于对话上下文构建，避免长会话每次全量拉回。
    """
    from sqlalchemy import select

    async with async_session_factory() as session:
        if limit is not None:
            # 先按时间倒序取最近 limit 条，再在应用层反转为升序
            recent = await session.execute(
                select(Conversation)
                .where(Conversation.session_id == session_id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            rows = list(reversed(recent.scalars().all()))
        else:
            result = await session.execute(
                select(Conversation).where(Conversation.session_id == session_id).order_by(Conversation.created_at)
            )
            rows = list(result.scalars().all())

    return [
        {
            "id": str(row.id),
            "role": row.role,
            "content": row.content,
            "model": row.model,
            "tokens": row.tokens,
            "metadata": row.metadata_ or {},
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def get_session_info(session_id: str) -> dict:
    """
    获取会话详情（包含消息列表和标题）

    用于前端加载会话时获取完整数据
    """
    messages = await get_history_db(session_id)

    # 生成会话标题：取第一条用户消息的前20字符
    title = "新对话"
    for msg in messages:
        if msg["role"] == "user":
            title = msg["content"][:20] + ("..." if len(msg["content"]) > 20 else "")
            break

    created_at = messages[0]["createdAt"] if messages else None

    return {
        "id": session_id,
        "title": title,
        "messages": messages,
        "createdAt": created_at,
    }


async def save_message(
    session_id: str,
    role: str,
    content: str,
    model: str | None = None,
    tokens: int | None = None,
    metadata: dict[str, object] | None = None,
    user_id: str | None = None,
):
    """
    保存单条消息到 PostgreSQL

    参数：
    - session_id: 会话ID
    - role: 角色（user/assistant/system）
    - content: 消息内容
    - model: 使用的模型
    - tokens: token 数
    - metadata: 附加元数据（如 sources、steps 等）
    """
    async with async_session_factory() as session:
        msg = Conversation(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            model=model,
            tokens=tokens,
            metadata_=metadata or {},
        )
        session.add(msg)
        await session.commit()
        return str(msg.id)


async def set_message_feedback(message_id: str, user_id: str, rating: str) -> bool:
    """保存助手消息反馈；只能修改当前用户自己的 assistant 消息。"""
    import uuid
    from sqlalchemy import select

    try:
        parsed_id = uuid.UUID(message_id)
    except (TypeError, ValueError, AttributeError):
        return False

    async with async_session_factory() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.id == parsed_id)
            .where(Conversation.user_id == user_id)
            .where(Conversation.role == "assistant")
        )
        message = result.scalar_one_or_none()
        if not message:
            return False
        metadata = dict(message.metadata_ or {})
        metadata["feedback"] = rating
        message.metadata_ = metadata
        await session.commit()
    return True


async def clear_history(session_id: str, user_id: str | None = None):
    """删除指定会话的所有消息（可选按 user_id 限定）"""
    from sqlalchemy import delete

    async with async_session_factory() as session:
        stmt = delete(Conversation).where(Conversation.session_id == session_id)
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        await session.execute(stmt)
        await session.commit()


def trim_history(history: List[dict], max_tokens=2000) -> List[dict]:
    """
    裁剪会话历史，保留近 max_tokens 个 token

    从最新消息开始保留，直到达到 token 上限
    """
    result: list[dict[str, object]] = []
    total = 0
    for msg in reversed(history):
        t = est_tokens(msg.get("content", ""))
        if total + t > max_tokens:
            break
        result.insert(0, msg)
        total += t
    return result


# ── 用户画像（PostgreSQL）───────────────────────────────────


async def get_profile(user_id: str) -> dict:
    """
    获取用户画像（从 PostgreSQL 的 metadata 中读取）

    简化实现：用户画像存储在 agent_configs 表
    """
    from sqlalchemy import select
    from ...models.entities import AgentConfig

    async with async_session_factory() as session:
        result = await session.execute(
            select(AgentConfig)
            .where(AgentConfig.name == f"profile_{user_id}")
            .where(AgentConfig.config_type == "profile")
        )
        row = result.scalar_one_or_none()

    if not row:
        return {}

    config = row.config_json
    return {
        "name": config.get("name"),
        "dept": config.get("dept"),
        "tech_level": config.get("tech_level"),
        "primary_stack": config.get("primary_stack"),
        "current_goal": config.get("current_goal"),
        "prefers_short": config.get("prefers_short"),
        "prefers_code": config.get("prefers_code"),
    }


async def get_profile_camel(user_id: str) -> dict:
    """
    获取用户画像（驼峰格式，用于 API 响应）
    """
    profile = await get_profile(user_id)
    return {
        "name": profile.get("name"),
        "dept": profile.get("dept"),
        "techLevel": profile.get("tech_level"),
        "primaryStack": profile.get("primary_stack"),
        "currentGoal": profile.get("current_goal"),
        "prefersShort": profile.get("prefers_short"),
        "prefersCode": profile.get("prefers_code"),
    }


async def save_profile(user_id: str, profile: dict):
    """保存用户画像到 PostgreSQL"""
    from ...models.entities import AgentConfig

    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AgentConfig)
            .where(AgentConfig.name == f"profile_{user_id}")
            .where(AgentConfig.config_type == "profile")
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.config_json = profile
            existing.version += 1
        else:
            session.add(
                AgentConfig(
                    config_type="profile",
                    name=f"profile_{user_id}",
                    config_json=profile,
                )
            )
        await session.commit()


async def clear_profile(user_id: str) -> None:
    """删除当前用户画像，清除操作在刷新和重新登录后仍然生效。"""
    from sqlalchemy import delete
    from ...models.entities import AgentConfig

    async with async_session_factory() as session:
        await session.execute(
            delete(AgentConfig)
            .where(AgentConfig.name == f"profile_{user_id}")
            .where(AgentConfig.config_type == "profile")
        )
        await session.commit()


def profile_to_context(profile):
    """
    将用户画像转换为 system prompt 上下文
    """
    if not profile:
        return ""

    parts = []
    if profile.get("name"):
        parts.append(f"用户姓名：{profile['name']}")
    if profile.get("dept"):
        parts.append(f"部门：{profile['dept']}")
    if profile.get("tech_level"):
        parts.append(f"技术水平：{profile['tech_level']}")
    if profile.get("primary_stack"):
        parts.append(f"技术栈：{', '.join(profile['primary_stack'])}")
    if profile.get("current_goal"):
        parts.append(f"当前目标：{profile['current_goal']}")
    if profile.get("prefers_short"):
        parts.append("偏好简短回答")
    if profile.get("prefers_code"):
        parts.append("偏好带代码示例的回答")

    return "\n\n用户背景：\n" + "\n".join(f"- {p}" for p in parts) if parts else ""


# ── 结构化画像提取 ──────────────────────────────────────────


class UserProfile(BaseModel):
    """用户画像数据模型"""

    has_info: bool
    name: Optional[str] = None
    dept: Optional[str] = None
    tech_level: Optional[Literal["初级", "中级", "高级", "架构师"]] = None
    primary_stack: Optional[List[str]] = None
    current_goal: Optional[str] = None
    prefers_short: Optional[bool] = None
    prefers_code: Optional[bool] = None


async def extract_and_update_profile(user_id, user_msg, ai_reply):
    """
    从对话中提取并更新用户画像
    """
    try:
        current = await get_profile(user_id)

        prompt = f"""从对话中提取用户信息，只填写有明确依据的字段。
当前已知画像：{current}
如果没有新信息，has_info 返回 false。

返回纯 JSON，格式：
{{"has_info": bool, "name": str|null, "dept": str|null, "tech_level": "初级"|"中级"|"高级"|"架构师"|null, "primary_stack": [str]|null, "current_goal": str|null, "prefers_short": bool|null, "prefers_code": bool|null}}"""

        form = await parse_with_retry(
            get_chat_model(),
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"用户说：{user_msg}\nAI回复：{ai_reply[:200]}"},
            ],
            UserProfile,
        )
        data = form.model_dump()

        if not data.get("has_info"):
            return

        # 合并更新
        updated = {**current}
        for key in ["name", "dept", "tech_level", "current_goal", "prefers_short", "prefers_code"]:
            if data.get(key) is not None:
                updated[key] = data[key]

        if data.get("primary_stack"):
            existing = current.get("primary_stack", [])
            updated["primary_stack"] = list(set(existing + data["primary_stack"]))

        await save_profile(user_id, updated)
    except Exception as err:
        logger.warn("profile extract failed", {"error": str(err), "userId": user_id})


def fire_and_forget_profile(user_id, user_msg, ai_reply):
    """异步更新画像，不阻塞响应"""
    import asyncio

    asyncio.create_task(extract_and_update_profile(user_id, user_msg, ai_reply))


# ── 兼容旧代码的同步接口（内存）─────────────────────────────

# 保留内存版本作为向后兼容，某些场景可能需要
_memory_store: dict[str, list[dict[str, object]]] = {}


def get_history_sync(session_id):
    """同步获取会话历史（从内存，仅向后兼容）"""
    return _memory_store.get(session_id, [])


def clear_history_sync(session_id):
    """同步删除会话（从内存，仅向后兼容）"""
    _memory_store.pop(session_id, None)


async def list_sessions_by_prefix(
    user_id: str | None,
    prefix: str,
    *,
    limit: int = 50,
    offset: int = 0,
    default_title: str = "新对话",
    title_len: int = 20,
) -> List[dict]:
    """按会话 ID 前缀分页返回会话列表（标题、消息数）。

    避免 N+1：先聚合分页取会话，再用一条 DISTINCT ON 查询批量取各会话首条 user 消息作标题。
    """
    from sqlalchemy import select, func

    async with async_session_factory() as session:
        grouped = (
            select(
                Conversation.session_id,
                func.count(Conversation.id).label("message_count"),
                func.min(Conversation.created_at).label("created_at"),
            )
            .where(Conversation.session_id.like(f"{prefix}%"))
            .group_by(Conversation.session_id)
            .order_by(func.min(Conversation.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
        if user_id:
            grouped = grouped.where(Conversation.user_id == user_id)
        agg_rows = (await session.execute(grouped)).all()

        session_ids = [row[0] for row in agg_rows]
        titles: dict[str, str] = {}
        if session_ids:
            # DISTINCT ON (session_id) + ORDER BY session_id, created_at → 每会话首条 user 消息
            title_stmt = (
                select(Conversation.session_id, Conversation.content)
                .where(Conversation.session_id.in_(session_ids))
                .where(Conversation.role == "user")
                .order_by(Conversation.session_id, Conversation.created_at)
                .distinct(Conversation.session_id)
            )
            if user_id:
                title_stmt = title_stmt.where(Conversation.user_id == user_id)
            for sid, content in (await session.execute(title_stmt)).all():
                titles[sid] = content

    sessions = []
    for row in agg_rows:
        sid = row[0]
        first_msg = titles.get(sid)
        title = default_title
        if first_msg:
            title = first_msg[:title_len] + ("..." if len(first_msg) > title_len else "")
        sessions.append(
            {
                "id": sid,
                "title": title,
                "messageCount": row[1],
                "createdAt": row[2].isoformat() if row[2] else None,
            }
        )
    return sessions


async def list_sessions(user_id: str | None = None, *, limit: int = 50, offset: int = 0) -> List[dict]:
    """获取当前用户的对话会话列表（仅 session_ 前缀，排除知识库/Agent 会话）。"""
    return await list_sessions_by_prefix(
        user_id,
        "session_",
        limit=limit,
        offset=offset,
        default_title="新对话",
        title_len=20,
    )
