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
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ..services.model import get_chat_model
from ..services.cache import cache
from ..services.chat.memory import (
    get_history, trim_history, clear_history,
    get_profile, get_profile_camel, profile_to_context, fire_and_forget_profile,
    list_sessions,
)
from ..middleware import ChatRequest, check_injection
from ..utils.errors import send_sse_error
from ..utils.logger import logger

chat_router = APIRouter()

# 内置角色预设：不同角色使用不同的 system prompt
ROLES = {
    'default': '你是 WorkMind AI，一个智能办公助手，回答简洁专业。',
    'tech': '你是资深技术顾问，精通 Vue3、React、Node.js 等前端技术栈。回答要有代码示例，说明清楚原理。',
    'hr': '你是 HR 助理，熟悉劳动法规、公司政策、绩效管理、招聘流程。回答要有温度，兼顾政策合规和员工关怀。',
    'legal': '你是法务助理，熟悉合同法、知识产权、劳动合同。回答要严谨，必要时建议咨询专业律师。',
}


def sse(event, data):
    """将数据格式化为 SSE 事件格式"""
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


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
        return StreamingResponse(
            iter([sse('error', {'message': '输入内容不符合使用规范', 'retryable': False})]),
            media_type='text/event-stream',
        )

    async def event_generator():
        try:
            # 1. system prompt + 用户画像
            base_system = ROLES.get(role, ROLES['default'])
            profile = get_profile(user_id)
            profile_ctx = profile_to_context(profile)
            system_prompt = base_system + profile_ctx

            # 2. 缓存检查：相同的 system prompt + message 命中缓存
            cached = cache.get(system_prompt, message)
            if cached:
                logger.info('cache hit', {'sessionId': session_id, 'msg': message[:30]})
                yield sse('cache_hit', {})
                content = cached['content']
                # 模拟打字机效果，逐字符推送
                for i in range(0, len(content), 3):
                    yield sse('token', {'token': content[i:i + 3]})
                    await asyncio.sleep(0.006)
                yield sse('done', {'fromCache': True})
                return

            # 3. 会话历史
            history = get_history(session_id)
            # 裁剪历史消息，保留近 2000 token
            trimmed = trim_history(history, 2000)

            # 4. 构建消息列表
            messages = [SystemMessage(system_prompt), *trimmed, HumanMessage(message)]

            yield sse('start', {'sessionId': session_id})

            # 5. 流式调用模型
            full_reply = ''
            input_tokens = 0
            output_tokens = 0

            async for chunk in get_chat_model().astream(messages):
                if chunk.content:
                    full_reply += chunk.content
                    yield sse('token', {'token': chunk.content})
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0

            # 6. 更新会话历史（保留最近 20 条）
            history.append(HumanMessage(message))
            history.append(AIMessage(full_reply))
            if len(history) > 20:
                del history[:2]

            # 7. 写入缓存
            cache.set(system_prompt, message, {
                'content': full_reply,
                'tokens': input_tokens + output_tokens,
            })

            # 8. 异步更新用户画像（不阻塞响应）
            fire_and_forget_profile(user_id, message, full_reply)

            yield sse('done', {'fromCache': False, 'inputTokens': input_tokens, 'outputTokens': output_tokens})
            logger.info('chat done', {
                'sessionId': session_id,
                'inputTokens': input_tokens,
                'outputTokens': output_tokens,
                'replyLen': len(full_reply),
            })
        except Exception as err:
            logger.error('chat error', {'error': str(err)})
            yield send_sse_error(err)

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@chat_router.get('/sessions')
async def get_sessions():
    """获取所有会话列表"""
    return {'sessions': list_sessions()}


@chat_router.delete('/sessions/{session_id}')
async def delete_session(session_id: str):
    """删除指定会话"""
    clear_history(session_id)
    return {'success': True}


@chat_router.get('/profile/{user_id}')
async def get_user_profile(user_id: str):
    """获取用户画像（camelCase 格式）"""
    return get_profile_camel(user_id)


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