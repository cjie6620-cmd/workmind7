"""
Agent 路由模块

提供任务 Agent 执行功能：
- POST /run: 启动 Agent 执行任务（SSE 流式）
- GET /tools: 获取可用工具列表
- GET /examples: 获取任务示例

Agent 基于 ReAct 模式（Reasoning + Acting）：
1. 理解任务需求
2. 决定是否调用工具
3. 执行工具获取结果
4. 根据结果决定下一步
5. 重复直到任务完成

最多执行 8 步工具调用，防止无限循环。
"""

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import get_current_user
from ..auth.models import UserContext
from ..services.agent.agent import run_agent, get_tool_list
from ..services.chat.memory import save_message, get_history_db, get_session_info
from ..services.config.config_service import list_configs as list_agent_configs
from ..middleware import check_injection
from ..schemas.requests import AgentRunRequest
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger
from ..utils.session_guard import assert_session_owner
from ..utils.agent_context import agent_user_scope

agent_router = APIRouter()


@agent_router.post('/run')
async def agent_run(
    req: AgentRunRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """
    启动 Agent 执行任务

    第一步：参数校验（空值、长度、Prompt 注入检测）
    第二步：创建异步队列，后台启动 Agent 执行任务
    第三步：SSE 流式推送事件（start → tool_call/tool_result/token → done）

    SSE 事件：
    - start: 任务开始
    - tool_call: 工具调用
    - tool_result: 工具执行结果
    - token: 响应 token
    - done: 执行完成
    """
    task = req.task.strip()
    session_id = req.sessionId or f'agent_{user.user_id}_{uuid.uuid4().hex[:12]}'

    await assert_session_owner(session_id, user.user_id)

    # 参数校验
    if not task:
        return JSONResponse(status_code=400, content={'error': {'message': '任务不能为空'}})
    if len(task) > 2000:
        return JSONResponse(status_code=400, content={'error': {'message': '任务描述过长，请简洁描述'}})
    if check_injection(task):
        return JSONResponse(status_code=400, content={'error': {'message': '输入内容不符合使用规范'}})

    # 使用队列 + 事件机制实现异步通信
    queue = asyncio.Queue()
    done_event = asyncio.Event()
    full_answer = []  # 收集完整回答

    async def collect_event(event_type, data):
        """收集 Agent 发出的事件到队列"""
        if event_type == 'token':
            full_answer.append(data.get('token', ''))
        await queue.put(sse_event(event_type, data))

    async def run_task():
        """后台执行 Agent 任务"""
        try:
            async with agent_user_scope(user.user_id):
                await save_message(session_id, 'user', task, user_id=user.user_id)
                await run_agent(task, collect_event)
        except asyncio.CancelledError:
            logger.info('agent route: task cancelled', {'sessionId': session_id})
            raise
        except Exception as err:
            logger.error('agent route: task failed', {'error': str(err)})
            await queue.put(sse_error(err))
        finally:
            done_event.set()
            answer_text = ''.join(full_answer)
            if answer_text:
                await save_message(session_id, 'assistant', answer_text, user_id=user.user_id)

    run_task_handle = asyncio.create_task(run_task())

    async def event_generator():
        """SSE 事件生成器"""
        yield sse_event('start', {'task': task, 'sessionId': session_id, 'timestamp': datetime.now().isoformat()})
        try:
            while not done_event.is_set() or not queue.empty():
                if await request.is_disconnected():
                    run_task_handle.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield item
                except asyncio.TimeoutError:
                    continue
            if not run_task_handle.cancelled() and done_event.is_set():
                yield sse_event('done', {'sessionId': session_id})
        finally:
            if not run_task_handle.done():
                run_task_handle.cancel()

    return EventSourceResponse(event_generator())


@agent_router.get('/tools')
async def agent_tools():
    """获取所有可用工具列表（名称、标签、描述）"""
    return {'tools': get_tool_list()}


@agent_router.get('/configs')
async def agent_config_list():
    """获取所有 Agent 配置（从 agent_configs 表）"""
    configs = await list_agent_configs('agent')
    # 转换为前端可直接使用的格式
    result = []
    for c in configs:
        cj = c['configJson']
        result.append({
            'id': c['id'],
            'name': c['name'],
            'description': cj.get('description', ''),
            'systemPrompt': cj.get('systemPrompt', ''),
            'tools': cj.get('tools', []),
            'modelParams': cj.get('modelParams', {}),
            'isActive': c['isActive'],
            'version': c['version'],
            'updatedAt': c['updatedAt'],
        })
    return {'configs': result}


@agent_router.get('/examples')
async def agent_examples():
    """
    获取任务示例

    展示 Agent 的典型使用场景：
    - 技术调研
    - 费用计算
    - 工期计算
    - 知识查询
    """
    return {
        'examples': [
            {
                'title': '技术调研',
                'task': '对比 Vue3 和 React 2024年的最新状态，分别查询它们的最新版本和主要特性，生成一份技术选型报告',
                'icon': '🔍',
            },
            {
                'title': '费用计算',
                'task': '我出差3天，酒店每晚580元，机票往返1200元，餐费每天150元，帮我计算总报销金额，并查询一下公司差旅报销标准',
                'icon': '💰',
            },
            {
                'title': '工期计算',
                'task': '项目计划从2024年3月1日开始，需要45个工作日完成，帮我计算预计完成日期，并生成一份项目时间轴摘要',
                'icon': '📅',
            },
            {
                'title': '知识查询',
                'task': '从知识库查询公司的年假政策，计算一下我今年还剩多少年假（假设今年已用6天，总共15天），并发送结果通知给HR',
                'icon': '📚',
            },
        ]
    }


# ── 报告管理 ─────────────────────────────────────────────────

@agent_router.get('/reports')
async def agent_reports(user: UserContext = Depends(get_current_user)):
    """列出当前用户 Agent 生成的报告（仅元数据）"""
    from ..services.agent.report_store import list_reports
    return {'reports': list_reports(user.user_id)}


@agent_router.get('/reports/{report_id}')
async def agent_report_detail(report_id: str, user: UserContext = Depends(get_current_user)):
    """获取单个报告的完整内容"""
    from ..services.agent.report_store import get_report
    report = get_report(report_id, user.user_id)
    if not report:
        return JSONResponse(status_code=404, content={'error': {'message': '报告不存在或已过期'}})
    return {'report': report}


@agent_router.get('/reports/{report_id}/download')
async def agent_report_download(report_id: str, user: UserContext = Depends(get_current_user)):
    """下载报告为 Markdown 文件"""
    from ..services.agent.report_store import get_report
    from fastapi.responses import Response
    report = get_report(report_id, user.user_id)
    if not report:
        return JSONResponse(status_code=404, content={'error': {'message': '报告不存在或已过期'}})
    title = report['meta']['title']
    content = report['content']
    return Response(
        content=content.encode('utf-8'),
        media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{title}.md"'.encode('utf-8')},
    )


@agent_router.delete('/reports/{report_id}')
async def agent_report_delete(report_id: str, user: UserContext = Depends(get_current_user)):
    """删除报告"""
    from ..services.agent.report_store import delete_report
    ok = delete_report(report_id, user.user_id)
    if not ok:
        return JSONResponse(status_code=500, content={'error': {'message': '删除失败'}})
    return {'success': True}


@agent_router.get('/history/{session_id}')
async def get_agent_history(session_id: str, user: UserContext = Depends(get_current_user)):
    """获取 Agent 任务历史"""
    await assert_session_owner(session_id, user.user_id)
    info = await get_session_info(session_id)
    return info


@agent_router.get('/sessions')
async def get_agent_sessions(user: UserContext = Depends(get_current_user)):
    """获取当前用户的 Agent 会话列表"""
    from sqlalchemy import select, func
    from ..core.database import async_session_factory
    from ..models.entities import Conversation

    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Conversation.session_id,
                func.count(Conversation.id).label('msg_count'),
                func.min(Conversation.created_at).label('created_at'),
            )
            .where(Conversation.session_id.like('agent_%'))
            .where(Conversation.user_id == user.user_id)
            .group_by(Conversation.session_id)
            .order_by(func.min(Conversation.created_at).desc())
        )
        rows = result.all()

        sessions = []
        for row in rows:
            sid = row[0]
            r = await session.execute(
                select(Conversation.content)
                .where(Conversation.session_id == sid)
                .where(Conversation.role == 'user')
                .order_by(Conversation.created_at)
                .limit(1)
            )
            first_msg = r.scalar_one_or_none()
            title = first_msg[:30] + ('...' if first_msg and len(first_msg) > 30 else '') if first_msg else 'Agent 任务'
            sessions.append({
                'id': sid,
                'title': title,
                'messageCount': row[1],
                'createdAt': row[2].isoformat() if row[2] else None,
            })

    return {'sessions': sessions}