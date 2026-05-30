"""
会话记忆管理模块

提供两大功能：
1. 短期记忆（会话历史）：存储在 PostgreSQL
2. 用户画像（跨会话）：存储在 PostgreSQL

特点：
- 异步操作，基于 asyncpg
- 自动裁剪避免超出 token 限制
"""

from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

from ..model import get_chat_model
from ...core.database import async_session_factory
from ...models.entities import Conversation
from ...utils.logger import logger
from ...utils.llm_parse import parse_with_retry


# ── Token 估算 ──────────────────────────────────────────────

def est_tokens(text=''):
    """
    估算文本 token 数量

    中文约 0.6 tokens/字符，英文约 0.25 tokens/字符
    """
    cn = sum(1 for c in text if '一' <= c <= '鿿')
    return int(cn * 0.6 + (len(text) - cn) * 0.25)


# ── 会话历史管理（PostgreSQL）───────────────────────────────

async def get_history_db(session_id: str) -> List[dict]:
    """
    获取指定会话的所有历史消息（从 PostgreSQL）

    返回消息列表，按时间升序
    """
    from sqlalchemy import select
    async with async_session_factory() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.created_at)
        )
        rows = result.scalars().all()

    return [
        {
            'id': str(row.id),
            'role': row.role,
            'content': row.content,
            'model': row.model,
            'tokens': row.tokens,
            'createdAt': row.created_at.isoformat() if row.created_at else None,
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
    title = '新对话'
    for msg in messages:
        if msg['role'] == 'user':
            title = msg['content'][:20] + ('...' if len(msg['content']) > 20 else '')
            break

    created_at = messages[0]['createdAt'] if messages else None

    return {
        'id': session_id,
        'title': title,
        'messages': messages,
        'createdAt': created_at,
    }


async def save_message(session_id: str, role: str, content: str, model: str = None, tokens: int = None, metadata: dict = None):
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
            role=role,
            content=content,
            model=model,
            tokens=tokens,
            metadata_=metadata or {},
        )
        session.add(msg)
        await session.commit()


async def save_messages_batch(session_id: str, messages: List[dict]):
    """
    批量保存消息到 PostgreSQL

    参数：
    - session_id: 会话ID
    - messages: 消息列表 [{role, content, model, tokens}, ...]
    """
    async with async_session_factory() as session:
        async with session.begin():
            for msg in messages:
                session.add(Conversation(
                    session_id=session_id,
                    role=msg['role'],
                    content=msg['content'],
                    model=msg.get('model'),
                    tokens=msg.get('tokens'),
                ))
        await session.commit()


async def clear_history(session_id: str):
    """删除指定会话的所有消息"""
    from sqlalchemy import delete
    async with async_session_factory() as session:
        await session.execute(
            delete(Conversation).where(Conversation.session_id == session_id)
        )
        await session.commit()


def trim_history(history: List[dict], max_tokens=2000) -> List[dict]:
    """
    裁剪会话历史，保留近 max_tokens 个 token

    从最新消息开始保留，直到达到 token 上限
    """
    result = []
    total = 0
    for msg in reversed(history):
        t = est_tokens(msg.get('content', ''))
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
            .where(AgentConfig.name == f'profile_{user_id}')
            .where(AgentConfig.config_type == 'profile')
        )
        row = result.scalar_one_or_none()

    if not row:
        return {}

    config = row.config_json
    return {
        'name': config.get('name'),
        'dept': config.get('dept'),
        'tech_level': config.get('tech_level'),
        'primary_stack': config.get('primary_stack'),
        'current_goal': config.get('current_goal'),
        'prefers_short': config.get('prefers_short'),
        'prefers_code': config.get('prefers_code'),
    }


async def get_profile_camel(user_id: str) -> dict:
    """
    获取用户画像（驼峰格式，用于 API 响应）
    """
    profile = await get_profile(user_id)
    return {
        'name': profile.get('name'),
        'dept': profile.get('dept'),
        'techLevel': profile.get('tech_level'),
        'primaryStack': profile.get('primary_stack'),
        'currentGoal': profile.get('current_goal'),
        'prefersShort': profile.get('prefers_short'),
        'prefersCode': profile.get('prefers_code'),
    }


async def save_profile(user_id: str, profile: dict):
    """保存用户画像到 PostgreSQL"""
    from ...models.entities import AgentConfig

    async with async_session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(AgentConfig)
            .where(AgentConfig.name == f'profile_{user_id}')
            .where(AgentConfig.config_type == 'profile')
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.config_json = profile
            existing.version += 1
        else:
            session.add(AgentConfig(
                config_type='profile',
                name=f'profile_{user_id}',
                config_json=profile,
            ))
        await session.commit()


def profile_to_context(profile):
    """
    将用户画像转换为 system prompt 上下文
    """
    if not profile:
        return ''

    parts = []
    if profile.get('name'):
        parts.append(f"用户姓名：{profile['name']}")
    if profile.get('dept'):
        parts.append(f"部门：{profile['dept']}")
    if profile.get('tech_level'):
        parts.append(f"技术水平：{profile['tech_level']}")
    if profile.get('primary_stack'):
        parts.append(f"技术栈：{', '.join(profile['primary_stack'])}")
    if profile.get('current_goal'):
        parts.append(f"当前目标：{profile['current_goal']}")
    if profile.get('prefers_short'):
        parts.append('偏好简短回答')
    if profile.get('prefers_code'):
        parts.append('偏好带代码示例的回答')

    return f'\n\n用户背景：\n' + '\n'.join(f'- {p}' for p in parts) if parts else ''


# ── 结构化画像提取 ──────────────────────────────────────────

class UserProfile(BaseModel):
    """用户画像数据模型"""
    has_info: bool
    name: Optional[str] = None
    dept: Optional[str] = None
    tech_level: Optional[Literal['初级', '中级', '高级', '架构师']] = None
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
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': f'用户说：{user_msg}\nAI回复：{ai_reply[:200]}'},
            ],
            UserProfile,
        )
        data = form.model_dump()

        if not data.get('has_info'):
            return

        # 合并更新
        updated = {**current}
        for key in ['name', 'dept', 'tech_level', 'current_goal', 'prefers_short', 'prefers_code']:
            if data.get(key) is not None:
                updated[key] = data[key]

        if data.get('primary_stack'):
            existing = current.get('primary_stack', [])
            updated['primary_stack'] = list(set(existing + data['primary_stack']))

        await save_profile(user_id, updated)
    except Exception as err:
        logger.warn('profile extract failed', {'error': str(err), 'userId': user_id})


def fire_and_forget_profile(user_id, user_msg, ai_reply):
    """异步更新画像，不阻塞响应"""
    import asyncio
    asyncio.create_task(extract_and_update_profile(user_id, user_msg, ai_reply))


# ── 兼容旧代码的同步接口（内存）─────────────────────────────

# 保留内存版本作为向后兼容，某些场景可能需要
_memory_store = {}


def get_history_sync(session_id):
    """同步获取会话历史（从内存，仅向后兼容）"""
    return _memory_store.get(session_id, [])


def clear_history_sync(session_id):
    """同步删除会话（从内存，仅向后兼容）"""
    _memory_store.pop(session_id, None)


async def list_sessions() -> List[dict]:
    """获取所有会话列表（从 PostgreSQL），包含标题和消息数"""
    from sqlalchemy import select, func

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Conversation.session_id,
                func.count(Conversation.id).label('message_count'),
                func.min(Conversation.created_at).label('created_at'),
            )
            .group_by(Conversation.session_id)
            .order_by(func.min(Conversation.created_at).desc())
        )
        rows = result.all()

        sessions = []
        for row in rows:
            session_id = row[0]
            # 获取第一条用户消息作为标题
            title = '新对话'
            r = await session.execute(
                select(Conversation.content)
                .where(Conversation.session_id == session_id)
                .where(Conversation.role == 'user')
                .order_by(Conversation.created_at)
                .limit(1)
            )
            first_msg = r.scalar_one_or_none()
            if first_msg:
                title = first_msg[:20] + ('...' if len(first_msg) > 20 else '')

            sessions.append({
                'id': session_id,
                'title': title,
                'messageCount': row[1],
                'createdAt': row[2].isoformat() if row[2] else None,
            })

    return sessions