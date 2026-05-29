"""
Chat 会话管理模块

提供对话相关的服务：
- memory: 会话历史管理与用户画像
"""

from .memory import (
    get_history_db, trim_history, clear_history,
    get_profile, get_profile_camel, profile_to_context, fire_and_forget_profile,
    list_sessions, save_message, get_session_info,
)

__all__ = [
    'get_history_db',
    'trim_history',
    'clear_history',
    'get_profile',
    'get_profile_camel',
    'profile_to_context',
    'fire_and_forget_profile',
    'list_sessions',
    'save_message',
    'get_session_info',
]