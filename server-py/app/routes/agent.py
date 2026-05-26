# Agent 路由：流式执行任务，实时推送每一步状态
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
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@agent_router.post('/run')
async def agent_run(req: dict):
    task = (req.get('task') or '').strip()

    if not task:
        return JSONResponse(status_code=400, content={'error': {'message': '任务不能为空'}})
    if len(task) > 2000:
        return JSONResponse(status_code=400, content={'error': {'message': '任务描述过长，请简洁描述'}})
    if check_injection(task):
        return JSONResponse(status_code=400, content={'error': {'message': '输入内容不符合使用规范'}})

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def collect_event(event_type, data):
        await queue.put(sse(event_type, data))

    async def run_task():
        try:
            await run_agent(task, collect_event)
        except Exception as err:
            logger.error('agent route error', {'error': str(err)})
            await queue.put(send_sse_error(err))
        finally:
            done_event.set()

    asyncio.create_task(run_task())

    async def event_generator():
        yield sse('start', {'task': task, 'timestamp': datetime.now().isoformat()})
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
    return {'tools': get_tool_list()}


@agent_router.get('/examples')
async def agent_examples():
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
