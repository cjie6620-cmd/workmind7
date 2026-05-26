# 工作流路由：启动/恢复工作流
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

active_workflows = {}


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


INTERMEDIATES_MAP = {
    'weekly_report': {'highlights': '提炼的亮点', 'risks': '风险/阻塞项'},
    'meeting_minutes': {'attendees': '参会人与议题', 'conclusions': '会议结论', 'action_items': 'Action Items'},
    'email_polish': {'purpose': '意图分析', 'issues': '发现的问题'},
    'prd_skeleton': {'features': '功能点', 'constraints': '约束条件'},
}


def _get_intermediates(values, workflow_id):
    field_map = INTERMEDIATES_MAP.get(workflow_id, {})
    return [{'key': k, 'label': label, 'value': values.get(k)}
            for k, label in field_map.items() if values.get(k)]


@workflow_router.get('/templates')
async def get_templates():
    return {'templates': list(WORKFLOW_META.values())}


@workflow_router.post('/start/stream')
async def start_workflow_stream(req: dict):
    workflow_id = req.get('workflowId')
    input_data = req.get('input', {})

    if not workflow_id or workflow_id not in WORKFLOW_BUILDERS:
        return JSONResponse(status_code=400, content={'error': {'message': f'未知工作流：{workflow_id}'}})

    thread_id = f'wf_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:4]}'
    wf_config = {'configurable': {'thread_id': thread_id}}

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def run():
        try:
            builder = WORKFLOW_BUILDERS[workflow_id]
            graph = builder()
            meta = WORKFLOW_META[workflow_id]

            active_workflows[thread_id] = {'graph': graph, 'meta': meta, 'config': wf_config}

            last_node = None
            async for event in graph.astream_events(input_data, config=wf_config, version='v2'):
                event_type = event['event']
                name = event.get('name', '')

                if event_type == 'on_chain_start' and name not in ('__start__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta and name != last_node:
                        last_node = name
                        await queue.put(sse('node_start', {'nodeId': name, 'label': node_in_meta['label']}))

                if event_type == 'on_chain_end' and name not in ('__end__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta:
                        output = event.get('data', {}).get('output', {})
                        preview = ''
                        if isinstance(output, dict):
                            first_val = next(iter(output.values()), '')
                            if isinstance(first_val, str) and first_val:
                                preview = first_val[:80] + ('...' if len(first_val) > 80 else '')
                        await queue.put(sse('node_done', {'nodeId': name, 'preview': preview}))

            state = graph.get_state(wf_config)

            if state.next:
                await queue.put(sse('paused', {
                    'threadId': thread_id,
                    'nextNode': state.next[0],
                    'intermediates': _get_intermediates(state.values, workflow_id),
                }))
            else:
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
            if feedback and feedback.strip():
                graph.update_state(wf_config, {'human_feedback': feedback})

            logger.info('workflow: resumed', {'threadId': thread_id, 'hasFeedback': bool(feedback)})

            last_node = None
            async for event in graph.astream_events(None, config=wf_config, version='v2'):
                event_type = event['event']
                name = event.get('name', '')

                if event_type == 'on_chain_start' and name not in ('__end__', 'LangGraph'):
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta and name != last_node:
                        last_node = name
                        await queue.put(sse('node_start', {'nodeId': name, 'label': node_in_meta['label']}))

                if event_type == 'on_chat_model_stream':
                    chunk = event.get('data', {}).get('chunk', {})
                    if chunk.get('content'):
                        await queue.put(sse('token', {'token': chunk['content']}))

                if event_type == 'on_chain_end':
                    node_in_meta = next((n for n in meta['nodes'] if n['id'] == name), None)
                    if node_in_meta:
                        await queue.put(sse('node_done', {'nodeId': name}))

            final_state = graph.get_state(wf_config)
            result = final_state.values.get(meta['resultKey'], '')
            await queue.put(sse('completed', {'threadId': thread_id, 'result': result}))

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
