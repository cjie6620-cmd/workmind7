"""
会话记忆管理模块

提供两大功能：
1. 短期记忆（会话历史）：
   - 存储当前对话的消息历史
   - 自动裁剪避免超出 token 限制

2. 用户画像（跨会话）：
   - 从对话中提取用户背景信息
   - 下次对话时注入上下文
   - 支持异步更新，不阻塞响应
"""

from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

from ..model import get_chat_model
from ...utils.logger import logger
from ...utils.llm_parse import parse_with_retry


# ── Token 估算 ──────────────────────────────────────────────

def est_tokens(text=''):
    """
    估算文本 token 数量

    中文约 0.6 tokens/字符，英文约 0.25 tokens/字符
    这是一个粗略估算，实际因模型而异
    """
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')  # 中文字符范围
    return int(cn * 0.6 + (len(text) - cn) * 0.25)


# ── 会话历史管理 ────────────────────────────────────────────

# 内存存储会话历史（生产环境建议用 Redis）
session_store = {}


def get_history(session_id):
    """获取会话历史，不存在则创建空列表"""
    if session_id not in session_store:
        session_store[session_id] = []
    return session_store[session_id]


def clear_history(session_id):
    """删除指定会话"""
    session_store.pop(session_id, None)


def trim_history(history, max_tokens=2000):
    """
    裁剪会话历史，保留近 max_tokens 个 token

    从最新消息开始保留，直到达到 token 上限
    """
    result = []
    total = 0
    for msg in reversed(history):
        t = est_tokens(msg.content or '')
        if total + t > max_tokens:
            break
        result.insert(0, msg)  # 保持顺序
        total += t
    return result


# ── 用户画像 ────────────────────────────────────────────────

# 内存存储用户画像（生产环境建议用数据库）
profile_store = {}


def get_profile(user_id):
    """获取用户画像（snake_case 格式，内部使用）"""
    return profile_store.get(user_id, {})


def get_profile_camel(user_id):
    """
    获取用户画像（camelCase 格式，API 返回使用）

    字段映射：
    - tech_level -> techLevel
    - primary_stack -> primaryStack
    """
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
    """
    将用户画像转换为 system prompt 上下文

    格式示例：
    用户背景：
    - 用户姓名：张三
    - 部门：技术部
    - 技术水平：中级
    - 偏好简短回答
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
    has_info: bool  # 是否有有效信息
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

    流程：
    1. 获取当前画像
    2. 调用 LLM 提取新信息
    3. 合并更新到画像
    """
    try:
        current = get_profile(user_id)

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
        if data.get('name'):
            updated['name'] = data['name']
        if data.get('dept'):
            updated['dept'] = data['dept']
        if data.get('tech_level'):
            updated['tech_level'] = data['tech_level']
        if data.get('current_goal'):
            updated['current_goal'] = data['current_goal']
        if data.get('prefers_short') is not None:
            updated['prefers_short'] = data['prefers_short']
        if data.get('prefers_code') is not None:
            updated['prefers_code'] = data['prefers_code']
        if data.get('primary_stack'):
            # 技术栈合并去重
            existing = current.get('primary_stack', [])
            updated['primary_stack'] = list(set(existing + data['primary_stack']))

        profile_store[user_id] = updated
    except Exception as err:
        logger.warn('profile extract failed', {'error': str(err), 'userId': user_id})


def fire_and_forget_profile(user_id, user_msg, ai_reply):
    """
    异步更新画像，不阻塞响应

    使用 asyncio.create_task 在后台执行
    """
    import asyncio
    asyncio.create_task(extract_and_update_profile(user_id, user_msg, ai_reply))


def list_sessions():
    """获取所有会话列表"""
    return [{'id': sid, 'messageCount': len(msgs)} for sid, msgs in session_store.items()]