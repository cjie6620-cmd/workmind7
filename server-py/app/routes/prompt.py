# Prompt 调试路由：测试 + A/B + 模板 CRUD
import json
import time as _time
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from ..services.model import create_chat_model
from ..services.prompt.prompt_service import (
    list_templates, get_template, save_template, delete_template, score_ab_test,
)
from ..utils.errors import send_sse_error
from ..utils.logger import logger

prompt_router = APIRouter()


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@prompt_router.post('/test/stream')
async def prompt_test_stream(req: dict):
    system_prompt = req.get('systemPrompt', '')
    user_message = (req.get('userMessage') or '').strip()
    temperature = req.get('temperature', 0.7)
    max_tokens = req.get('maxTokens', 1000)

    if not user_message:
        return JSONResponse(status_code=400, content={'error': {'message': '测试消息不能为空'}})

    async def event_generator():
        try:
            test_model = create_chat_model(temperature=temperature, streaming=True)

            messages = []
            if system_prompt.strip():
                messages.append(SystemMessage(system_prompt))
            messages.append(HumanMessage(user_message))

            yield sse('start', {'temperature': temperature, 'maxTokens': max_tokens})

            full_reply = ''
            input_tokens = 0
            output_tokens = 0
            start_ms = int(_time.time() * 1000)

            async for chunk in test_model.astream(messages):
                if chunk.content:
                    full_reply += chunk.content
                    yield sse('token', {'token': chunk.content})
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0

            latency_ms = int(_time.time() * 1000) - start_ms

            yield sse('done', {
                'latencyMs': latency_ms,
                'inputTokens': input_tokens,
                'outputTokens': output_tokens,
                'totalTokens': input_tokens + output_tokens,
                'costCNY': ((input_tokens / 1e6 * 0.27) + (output_tokens / 1e6 * 1.10)) * 7.2,
            })

            logger.info('prompt test done', {'latencyMs': latency_ms, 'inputTokens': input_tokens})
        except Exception as err:
            logger.error('prompt test error', {'error': str(err)})
            yield send_sse_error(err)

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@prompt_router.post('/ab-test')
async def prompt_ab_test(req: dict):
    question = (req.get('question') or '').strip()
    system_prompt_a = req.get('systemPromptA', '')
    system_prompt_b = req.get('systemPromptB', '')
    temperature = req.get('temperature', 0)
    max_tokens = req.get('maxTokens', 800)

    if not question:
        return JSONResponse(status_code=400, content={'error': {'message': '测试问题不能为空'}})

    try:
        test_model = create_chat_model(temperature=temperature)

        msgs_a = ([SystemMessage(system_prompt_a)] if system_prompt_a else []) + [HumanMessage(question)]
        msgs_b = ([SystemMessage(system_prompt_b)] if system_prompt_b else []) + [HumanMessage(question)]
        res_a, res_b = await test_model.ainvoke(msgs_a), await test_model.ainvoke(msgs_b)

        answer_a = res_a.content
        answer_b = res_b.content

        evaluation = await score_ab_test(question, answer_a, answer_b)

        return {'answerA': answer_a, 'answerB': answer_b, 'evaluation': evaluation}
    except Exception as err:
        logger.error('ab test error', {'error': str(err)})
        return JSONResponse(status_code=500, content={'error': {'message': '测试失败，请重试'}})


# ── 模板 CRUD ───────────────────────────────────────────────

@prompt_router.get('/templates')
async def list_prompt_templates():
    return {'templates': list_templates()}


@prompt_router.get('/templates/{template_id}')
async def get_prompt_template(template_id: str):
    t = get_template(template_id)
    if not t:
        return JSONResponse(status_code=404, content={'error': {'message': '模板不存在'}})
    return t


@prompt_router.post('/templates')
async def create_prompt_template(req: dict):
    name = (req.get('name') or '').strip()
    system_prompt = (req.get('systemPrompt') or '').strip()
    if not name or not system_prompt:
        return JSONResponse(status_code=400, content={'error': {'message': '模板名称和内容不能为空'}})
    template = save_template(name, system_prompt, req.get('description', ''), req.get('tags', []))
    return {'success': True, 'template': template}


@prompt_router.put('/templates/{template_id}')
async def update_prompt_template(template_id: str, req: dict):
    template = save_template(
        req.get('name', ''), req.get('systemPrompt', ''),
        req.get('description', ''), req.get('tags', []),
        existing_id=template_id,
    )
    return {'success': True, 'template': template}


@prompt_router.delete('/templates/{template_id}')
async def remove_prompt_template(template_id: str):
    try:
        delete_template(template_id)
        return {'success': True}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})
