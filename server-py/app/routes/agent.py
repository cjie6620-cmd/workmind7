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
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse

from ..services.agent.agent import run_agent, get_tool_list
from ..middleware import check_injection
from ..utils.errors import send_sse_error
from ..utils.logger import logger

agent_router = APIRouter()


def sse(event, data):
    """将数据格式化为 SSE 事件格式"""
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@agent_router.post('/run')
async def agent_run(req: dict):
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
    task = (req.get('task') or '').strip()

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

    async def collect_event(event_type, data):
        """收集 Agent 发出的事件到队列"""
        await queue.put(sse(event_type, data))

    async def run_task():
        """后台执行 Agent 任务"""
        try:
            await run_agent(task, collect_event)
        except Exception as err:
            logger.error('agent route error', {'error': str(err)})
            await queue.put(send_sse_error(err))
        finally:
            done_event.set()

    # 异步启动任务，不阻塞响应
    asyncio.create_task(run_task())

    async def event_generator():
        """SSE 事件生成器"""
        yield sse('start', {'task': task, 'timestamp': datetime.now().isoformat()})
        # 循环直到任务完成且队列清空
        while not done_event.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except asyncio.TimeoutError:
                continue

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@agent_router.get('/tools')
async def agent_tools():
    """获取所有可用工具列表（名称、标签、描述）"""
    return {'tools': get_tool_list()}


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