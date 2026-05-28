"""
工作流路由模块

提供内容工作流的启动和恢复功能：
- GET /templates: 获取工作流模板列表
- POST /start/stream: 启动工作流（SSE 流式）
- POST /resume/stream: 恢复被中断的工作流（SSE 流式）

工作流特点：
- 基于 LangGraph 状态机编排
- 支持人工审核节点（interrupt）
- 中断后可恢复并提供反馈
- 流式推送每个节点的状态

内置工作流：
- weekly_report: 周报生成
- meeting_minutes: 会议纪要
- email_polish: 邮件润色
- prd_skeleton: PRD 骨架
"""

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from ..services.workflow.workflows import WORKFLOW_BUILDERS, WORKFLOW_META
from ..utils.errors import send_sse_error
from ..utils.logger import logger

workflow_router = APIRouter()

# 存储活跃工作流实例（thread_id -> {graph, meta, config}）
active_workflows = {}


def sse(event, data):
    """将数据格式化为 SSE 事件格式"""
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


# 工作流中间结果字段映射
INTERMEDIATES_MAP = {
    'weekly_report': {'highlights': '提炼的亮点', 'risks': '风险/阻塞项'},
    'meeting_minutes': {'attendees': '参会人与议题', 'conclusions': '会议结论', 'action_items': 'Action Items'},
    'email_polish': {'purpose': '意图分析', 'issues': '发现的问题'},
    'prd_skeleton': {'features': '功能点', 'constraints': '约束条件'},
}


def _get_intermediates(values, workflow_id):
    """从工作流状态中提取中间结果，供前端展示"""
    field_map = INTERMEDIATES_MAP.get(workflow_id, {})
    return [{'key': k, 'label': label, 'value': values.get(k)}
            for k, label in field_map.items() if values.get(k)]


@workflow_router.get('/templates')
async def get_templates():
    """获取所有工作流模板元信息"""
    return {'templates': list(WORKFLOW_META.values())}


@workflow_router.post('/start/stream')
async def start_workflow_stream(req: dict):
    """
    启动工作流

    第一步：校验工作流 ID，生成线程 ID
    第二步：构建工作流图，监听 LangGraph 事件流
    第三步：按节点顺序推送状态（node_start → node_done）
    第四步：检查是否中断（人工审核节点），推送暂停或完成

    SSE 事件：
    - start: 工作流开始
    - node_start: 节点开始执行
    - node_done: 节点执行完成
    - paused: 等待人工审核（人工节点）
    - completed: 工作流完成
    """
    workflow_id = req.get('workflowId')
    input_data = req.get('input', {})

    if not workflow_id or workflow_id not in WORKFLOW_BUILDERS:
        return JSONResponse(status_code=400, content={'error': {'message': f'未知工作流：{workflow_id}'}})

    # 生成唯一线程 ID，用于状态持久化
    thread_id = f'wf_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:4]}'
    wf_config = {'configurable': {'thread_id': thread_id}}

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def run():
        try:
            builder = WORKFLOW_BUILDERS[workflow_id]
            graph = builder()
            meta = WORKFLOW_META[workflow_id]

            # 保存工作流实例，用于后续恢复
            active_workflows[thread_id] = {'graph': graph, 'meta': meta, 'config': wf_config}

            last_node = None
            # 监听 LangGraph 事件流
            async for event in graph.astream_events(input_data, config=wf_config, version='v2'):
                event_type = event['event']
                name = event.get('name', '')
                data = event.get('data', {})
                if not isinstance(data, dict):
                    data = {}

                # 节点开始执行
                if event_type == 'on_chain_start' and name not in ('__start__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta and name != last_node:
                        last_node = name
                        await queue.put(sse('node_start', {'nodeId': name, 'label': node_in_meta['label']}))

                # 节点执行完成
                if event_type == 'on_chain_end' and name not in ('__end__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta:
                        output = data.get('output', {})
                        # 提取输出预览（前80字符）
                        preview = ''
                        if isinstance(output, dict):
                            first_val = next(iter(output.values()), '')
                            if isinstance(first_val, str) and first_val:
                                preview = first_val[:80] + ('...' if len(first_val) > 80 else '')
                        await queue.put(sse('node_done', {'nodeId': name, 'preview': preview}))

            # 工作流状态检查：是否有人工审核节点等待
            state = graph.get_state(wf_config)

            if state.next:
                # 有人工节点中断，返回中间结果供用户确认
                await queue.put(sse('paused', {
                    'threadId': thread_id,
                    'nextNode': state.next[0],
                    'intermediates': _get_intermediates(state.values, workflow_id),
                }))
            else:
                # 工作流正常完成
                result = state.values.get(meta['resultKey'], '')
                await queue.put(sse('completed', {'threadId': thread_id, 'result': result}))

        except Exception as err:
            logger.error('workflow: start error', {'error': str(err), 'threadId': thread_id})
            await queue.put(send_sse_error(err))
        finally:
            done_event.set()

    asyncio.create_task(run())

    async def event_generator():
        yield sse('start', {'threadId': thread_id, 'workflowId': workflow_id})
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


@workflow_router.post('/resume/stream')
async def resume_workflow_stream(req: dict):
    """
    恢复被中断的工作流

    第一步：校验线程 ID，查找工作流实例
    第二步：注入用户反馈到工作流状态
    第三步：重新执行工作流，流式推送节点状态和 token
    第四步：推送最终结果，清理工作流实例
    """
    thread_id = req.get('threadId')
    feedback = req.get('feedback', '')

    wf = active_workflows.get(thread_id)
    if not wf:
        return JSONResponse(status_code=404, content={'error': {'message': '工作流不存在或已过期，请重新启动'}})

    graph = wf['graph']
    meta = wf['meta']
    wf_config = wf['config']

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def run():
        try:
            # 更新状态：注入用户反馈
            if feedback and feedback.strip():
                graph.update_state(wf_config, {'human_feedback': feedback})

            logger.info('workflow: resumed', {'threadId': thread_id, 'hasFeedback': bool(feedback)})

            last_node = None
            async for event in graph.astream_events(None, config=wf_config, version='v2'):
                event_type = event['event']
                name = event.get('name', '')
                data = event.get('data', {})
                if not isinstance(data, dict):
                    data = {}

                if event_type == 'on_chain_start' and name not in ('__end__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta and name != last_node:
                        last_node = name
                        await queue.put(sse('node_start', {'nodeId': name, 'label': node_in_meta['label']}))

                if event_type == 'on_chat_model_stream':
                    chunk = data.get('chunk')
                    if chunk and chunk.content:
                        await queue.put(sse('token', {'token': chunk.content}))

                if event_type == 'on_chain_end':
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta:
                        await queue.put(sse('node_done', {'nodeId': name}))

            final_state = graph.get_state(wf_config)
            result = final_state.values.get(meta['resultKey'], '')
            await queue.put(sse('completed', {'threadId': thread_id, 'result': result}))

            # 清理已完成的工作流实例
            active_workflows.pop(thread_id, None)
            logger.info('workflow: completed', {'threadId': thread_id})

        except Exception as err:
            logger.error('workflow: resume error', {'error': str(err), 'threadId': thread_id})
            await queue.put(send_sse_error(err))
        finally:
            done_event.set()

    asyncio.create_task(run())

    async def event_generator():
        yield sse('resumed', {'threadId': thread_id})
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