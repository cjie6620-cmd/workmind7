# 会话记忆管理：短期记忆（当前对话历史）+ 用户画像（跨会话）
import asyncio

from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

from ..model import chat_model
from ...utils.logger import logger


# ── Token 估算 ──────────────────────────────────────────────

def est_tokens(text=''):
    cn = sum(1 for c in text if '一' <= c <= '鿿')
    return int(cn * 0.6 + (len(text) - cn) * 0.25)


# ── 会话历史管理 ────────────────────────────────────────────

session_store = {}


def get_history(session_id):
    if session_id not in session_store:
        session_store[session_id] = []
    return session_store[session_id]


def clear_history(session_id):
    session_store.pop(session_id, None)


def trim_history(history, max_tokens=2000):
    result = []
    total = 0
    for msg in reversed(history):
        t = est_tokens(msg.content or '')
        if total + t > max_tokens:
            break
        result.insert(0, msg)
        total += t
    return result


# ── 用户画像 ────────────────────────────────────────────────

profile_store = {}


def get_profile(user_id):
    return profile_store.get(user_id, {})


def get_profile_camel(user_id):
    """返回 camelCase 格式的画像，供 API 接口使用"""
    profile = profile_store.get(user_id, {})
    if not profile:
        return {}
    return {
        'name': profile.get('name'),
        'dept': profile.get('dept'),
        'techLevel': profile.get('tech_level'),
        'primaryStack': profile.get('primary_stack'),
        'currentGoal': profile.get('current_goal'),
        'prefersShort': profile.get('prefers_short'),
        'prefersCode': profile.get('prefers_code'),
    }


def profile_to_context(profile):
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
    has_info: bool
    name: Optional[str] = None
    dept: Optional[str] = None
    tech_level: Optional[Literal['初级', '中级', '高级', '架构师']] = None
    primary_stack: Optional[List[str]] = None
    current_goal: Optional[str] = None
    prefers_short: Optional[bool] = None
    prefers_code: Optional[bool] = None


async def extract_and_update_profile(user_id, user_msg, ai_reply):
    try:
        current = get_profile(user_id)

        extract_model = chat_model.with_structured_output(UserProfile)
        result = await extract_model.ainvoke([
            {
                'role': 'system',
                'content': f'从对话中提取用户信息，只填写有明确依据的字段。\n当前已知画像：{current}\n如果没有新信息，has_info 返回 false。',
            },
            {
                'role': 'user',
                'content': f'用户说：{user_msg}\nAI回复：{ai_reply[:200]}',
            },
        ])

        if not result.has_info:
            return

        updated = {**current}
        if result.name:
            updated['name'] = result.name
        if result.dept:
            updated['dept'] = result.dept
        if result.tech_level:
            updated['tech_level'] = result.tech_level
        if result.current_goal:
            updated['current_goal'] = result.current_goal
        if result.prefers_short is not None:
            updated['prefers_short'] = result.prefers_short
        if result.prefers_code is not None:
            updated['prefers_code'] = result.prefers_code
        if result.primary_stack:
            existing = current.get('primary_stack', [])
            updated['primary_stack'] = list(set(existing + result.primary_stack))

        profile_store[user_id] = updated
    except Exception as err:
        logger.warn('profile extract failed', {'error': str(err), 'userId': user_id})


def fire_and_forget_profile(user_id, user_msg, ai_reply):
    """异步更新画像，不阻塞响应"""
    asyncio.create_task(extract_and_update_profile(user_id, user_msg, ai_reply))


def list_sessions():
    return [{'id': sid, 'messageCount': len(msgs)} for sid, msgs in session_store.items()]
