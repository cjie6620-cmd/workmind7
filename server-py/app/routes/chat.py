"""
对话路由模块

提供智能对话功能：
- POST /stream: 流式对话（支持缓存、会话历史、用户画像）
- GET /sessions: 获取会话列表
- DELETE /sessions/{session_id}: 删除会话
- GET /profile/{user_id}: 获取用户画像
- GET /roles: 获取内置角色列表

核心特性：
- SSE 流式响应，实时推送 token
- 精确缓存：相同 system prompt + message 返回缓存结果
- 多角色预设：default/tech/hr/legal
- 用户画像：自动从对话中提取用户背景信息
"""

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from sse_starlette.sse import EventSourceResponse

from ..services.model import get_chat_model
from ..services.cache import cache
from ..services.chat.memory import (
    get_history_db, trim_history, clear_history,
    get_profile, get_profile_camel, profile_to_context, fire_and_forget_profile,
    list_sessions, save_message, get_session_info,
)
from ..middleware import ChatRequest, check_injection
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger

chat_router = APIRouter()

# 内置角色预设：不同角色使用不同的 system prompt
ROLES = {
    'default': '你是 WorkMind AI，一个智能办公助手，回答简洁专业。',
    'tech': '你是资深技术顾问，精通 Vue3、React、Node.js 等前端技术栈。回答要有代码示例，说明清楚原理。',
    'hr': '你是 HR 助理，熟悉劳动法规、公司政策、绩效管理、招聘流程。回答要有温度，兼顾政策合规和员工关怀。',
    'legal': '你是法务助理，熟悉合同法、知识产权、劳动合同。回答要严谨，必要时建议咨询专业律师。',
}


@chat_router.post('/stream')
async def chat_stream(req: ChatRequest):
    """
    流式对话接口

    第一步：安全检查（Prompt 注入检测）
    第二步：构建 system prompt（含用户画像）
    第三步：缓存检查（命中则直接返回）
    第四步：获取会话历史并裁剪
    第五步：流式调用模型
    第六步：更新会话历史
    第七步：写入缓存
    第八步：异步更新用户画像

    SSE 事件：
    - start: 开始响应
    - cache_hit: 命中缓存
    - token: 增量 token
    - done: 响应完成
    """
    message = req.message
    session_id = req.sessionId
    role = req.role
    user_id = req.userId

    # 安全检查：Prompt 注入检测
    if check_injection(message):
        return JSONResponse(status_code=400, content={'error': {'message': '输入内容不符合使用规范'}})

    async def event_generator():
        try:
            # 1. system prompt + 用户画像
            base_system = ROLES.get(role, ROLES['default'])
            profile = await get_profile(user_id)
            profile_ctx = profile_to_context(profile)
            system_prompt = base_system + profile_ctx

            # 2. 缓存检查：相同的 system prompt + message 命中缓存
            cached = cache.get(system_prompt, message)
            if cached:
                logger.info('cache hit', {'sessionId': session_id, 'msg': message[:30]})
                yield sse_event('cache_hit', {})
                content = cached['content']
                # 模拟打字机效果，逐字符推送
                for i in range(0, len(content), 3):
                    yield sse_event('token', {'token': content[i:i + 3]})
                    await asyncio.sleep(0.006)
                yield sse_event('done', {'fromCache': True})
                return

            # 3. 会话历史（从数据库获取并转换为 dict 格式用于裁剪）
            raw_history = await get_history_db(session_id)
            history_msgs = []
            for msg in raw_history:
                history_msgs.append({
                    'role': msg['role'],
                    'content': msg['content'],
                })

            # 裁剪历史消息，保留近 2000 token
            trimmed = trim_history(history_msgs, 2000)

            # 4. 构建消息列表
            messages = [SystemMessage(system_prompt), *trimmed, HumanMessage(message)]

            yield sse_event('start', {'sessionId': session_id})

            # 5. 流式调用模型
            full_reply = ''
            input_tokens = 0
            output_tokens = 0

            async for chunk in get_chat_model().astream(messages):
                if chunk.content:
                    full_reply += chunk.content
                    yield sse_event('token', {'token': chunk.content})
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0

            # 6. 保存消息到数据库
            await save_message(session_id, 'user', message)
            await save_message(session_id, 'assistant', full_reply, model='deepseek-chat', tokens=output_tokens)

            # 7. 写入缓存
            cache.set(system_prompt, message, {
                'content': full_reply,
                'tokens': input_tokens + output_tokens,
            })

            # 8. 异步更新用户画像（不阻塞响应）
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
async def get_sessions():
    """获取所有会话列表"""
    sessions = await list_sessions()
    return {'sessions': sessions}


@chat_router.post('/sessions')
async def create_session():
    """创建新会话"""
    session_id = f'session_{int(time.time() * 1000)}'
    return {'id': session_id, 'title': '新对话', 'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ')}


@chat_router.get('/history/{session_id}')
async def get_history_endpoint(session_id: str):
    """获取指定会话的历史消息"""
    try:
        messages = await get_history_db(session_id)
    except Exception:
        # 数据库异常时返回空列表，避免前端加载失败
        messages = []
    return {'messages': messages}


@chat_router.delete('/sessions/{session_id}')
async def delete_session(session_id: str):
    """删除指定会话"""
    clear_history(session_id)
    return {'success': True}


@chat_router.get('/profile/{user_id}')
async def get_user_profile(user_id: str):
    """获取用户画像（camelCase 格式）"""
    return await get_profile_camel(user_id)


@chat_router.get('/roles')
async def get_roles():
    """
    获取内置角色列表

    返回：角色 ID、名称、图标、描述
    """
    return {
        'roles': [
            {'id': 'default', 'label': '通用助手', 'icon': '🤖', 'desc': '日常问答、通用任务'},
            {'id': 'tech', 'label': '技术顾问', 'icon': '💻', 'desc': '代码、架构、技术方案'},
            {'id': 'hr', 'label': 'HR 助理', 'icon': '📋', 'desc': '人事政策、绩效、招聘'},
            {'id': 'legal', 'label': '法务助理', 'icon': '⚖️', 'desc': '合同、合规、法律问题'},
        ]
    }