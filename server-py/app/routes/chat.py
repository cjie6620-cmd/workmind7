"""
对话路由模块

提供智能对话功能：
- POST /stream: 流式对话（支持缓存、会话历史、用户画像）
- GET /sessions: 获取会话列表
- DELETE /sessions/{session_id}: 删除会话
- GET /profile: 获取当前用户画像
- GET /roles: 获取内置角色列表
"""

import asyncio
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..services.model import get_chat_model
from ..services.cache import cache
from ..services.chat.memory import (
    get_history_db, trim_history, clear_history,
    get_profile, get_profile_camel, profile_to_context, fire_and_forget_profile,
    list_sessions, save_message,
)
from ..middleware import ChatRequest, check_injection
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger
from ..utils.session_guard import assert_session_owner, normalize_chat_session_id

chat_router = APIRouter()

ROLES = {
    'default': '你是 Mr.Chen AI，一个智能办公助手，回答简洁专业。',
    'tech': '你是资深技术顾问，精通 Vue3、React、Node.js 等前端技术栈。回答要有代码示例，说明清楚原理。',
    'hr': '你是 HR 助理，熟悉劳动法规、公司政策、绩效管理、招聘流程。回答要有温度，兼顾政策合规和员工关怀。',
    'legal': '你是法务助理，熟悉合同法、知识产权、劳动合同。回答要严谨，必要时建议咨询专业律师。',
}


@chat_router.post('/stream')
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """流式对话接口"""
    message = req.message
    session_id = normalize_chat_session_id(req.sessionId, user.user_id)
    role = req.role
    user_id = user.user_id

    if check_injection(message):
        return JSONResponse(status_code=400, content={'error': {'message': '输入内容不符合使用规范'}})

    await assert_session_owner(session_id, user_id)

    async def event_generator():
        try:
            base_system = ROLES.get(role, ROLES['default'])
            profile = await get_profile(user_id)
            profile_ctx = profile_to_context(profile)
            system_prompt = base_system + profile_ctx

            cached = cache.get(system_prompt, message)
            if cached:
                logger.info('cache hit', {'sessionId': session_id, 'msg': message[:30]})
                yield sse_event('cache_hit', {})
                content = cached['content']
                for i in range(0, len(content), 3):
                    yield sse_event('token', {'token': content[i:i + 3]})
                    await asyncio.sleep(0.006)
                yield sse_event('done', {'fromCache': True})
                return

            raw_history = await get_history_db(session_id)
            history_msgs = [{'role': msg['role'], 'content': msg['content']} for msg in raw_history]
            trimmed = trim_history(history_msgs, 2000)
            messages = [SystemMessage(system_prompt), *trimmed, HumanMessage(message)]

            yield sse_event('start', {'sessionId': session_id})

            full_reply = ''
            input_tokens = 0
            output_tokens = 0

            async for chunk in get_chat_model().astream(messages):
                if await request.is_disconnected():
                    break
                if chunk.content:
                    full_reply += chunk.content
                    yield sse_event('token', {'token': chunk.content})
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0

            if await request.is_disconnected():
                return

            await save_message(session_id, 'user', message, user_id=user_id)
            await save_message(
                session_id, 'assistant', full_reply,
                model='deepseek-chat', tokens=output_tokens, user_id=user_id,
            )

            cache.set(system_prompt, message, {
                'content': full_reply,
                'tokens': input_tokens + output_tokens,
            })

            fire_and_forget_profile(user_id, message, full_reply)

            yield sse_event('done', {'fromCache': False, 'inputTokens': input_tokens, 'outputTokens': output_tokens})
            logger.info('chat done', {
                'sessionId': session_id,
                'inputTokens': input_tokens,
                'outputTokens': output_tokens,
                'replyLen': len(full_reply),
            })
        except Exception as err:
            logger.error('chat error', {'error': str(err)})
            yield sse_error(err)

    return EventSourceResponse(event_generator())


@chat_router.get('/sessions')
async def get_sessions(user: UserContext = Depends(get_current_user)):
    """获取当前用户的会话列表"""
    sessions = await list_sessions(user_id=user.user_id)
    return {'sessions': sessions}


@chat_router.post('/sessions')
async def create_session(user: UserContext = Depends(get_current_user)):
    """创建新会话"""
    session_id = f'session_{user.user_id}_{int(time.time() * 1000)}'
    return {'id': session_id, 'title': '新对话', 'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ')}


@chat_router.get('/history/{session_id}')
async def get_history_endpoint(session_id: str, user: UserContext = Depends(get_current_user)):
    """获取指定会话的历史消息"""
    await assert_session_owner(session_id, user.user_id)
    try:
        messages = await get_history_db(session_id)
    except Exception:
        messages = []
    return {'messages': messages}


@chat_router.delete('/sessions/{session_id}')
async def delete_session(session_id: str, user: UserContext = Depends(get_current_user)):
    """删除指定会话"""
    await assert_session_owner(session_id, user.user_id)
    await clear_history(session_id, user_id=user.user_id)
    return {'success': True}


@chat_router.get('/profile')
async def get_user_profile(user: UserContext = Depends(get_current_user)):
    """获取当前用户画像"""
    return await get_profile_camel(user.user_id)


@chat_router.get('/roles')
async def get_roles():
    """获取内置角色列表"""
    return {
        'roles': [
            {'id': 'default', 'label': '通用助手', 'icon': '🤖', 'desc': '日常问答、通用任务'},
            {'id': 'tech', 'label': '技术顾问', 'icon': '💻', 'desc': '代码、架构、技术方案'},
            {'id': 'hr', 'label': 'HR 助理', 'icon': '📋', 'desc': '人事政策、绩效、招聘'},
            {'id': 'legal', 'label': '法务助理', 'icon': '⚖️', 'desc': '合同、合规、法律问题'},
        ]
    }
