"""
Prompt 调试路由模块

提供 Prompt 模板管理和测试功能：
- POST /test/stream: 测试 Prompt 效果（SSE 流式）
- POST /ab-test/stream: A/B 测试对比两个 Prompt（SSE 流式）
- GET /templates: 获取模板列表
- GET /templates/{template_id}: 获取模板详情
- POST /templates: 创建模板
- PUT /templates/{template_id}: 更新模板
- DELETE /templates/{template_id}: 删除模板

特点：
- 支持自定义 temperature、maxTokens
- 自动计算 Token 消耗和费用
- A/B 测试自动评分对比
- 模板版本管理
"""

import asyncio
import time as _time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage, SystemMessage
from sse_starlette.sse import EventSourceResponse

from ..services.model import create_chat_model
from ..services.prompt.prompt_service import (
    list_templates, get_template, save_template, delete_template, score_ab_test,
)
from ..utils.sse import sse_event, sse_error
from ..utils.logger import logger

prompt_router = APIRouter()


@prompt_router.post('/test/stream')
async def prompt_test_stream(req: dict):
    """
    测试 Prompt 接口

    第一步：校验测试消息，创建独立模型实例
    第二步：构建消息列表（可选 system prompt + user message）
    第三步：流式调用模型，实时推送 token
    第四步：统计 Token 用量，计算费用并返回
    """
    system_prompt = req.get('systemPrompt', '')
    user_message = (req.get('userMessage') or '').strip()
    temperature = req.get('temperature', 0.7)
    max_tokens = req.get('maxTokens', 1000)

    if not user_message:
        return JSONResponse(status_code=400, content={'error': {'message': '测试消息不能为空'}})

    async def event_generator():
        try:
            # 创建独立模型实例用于测试
            test_model = create_chat_model(temperature=temperature, streaming=True)

            messages = []
            if system_prompt.strip():
                messages.append(SystemMessage(system_prompt))
            messages.append(HumanMessage(user_message))

            yield sse_event('start', {'temperature': temperature, 'maxTokens': max_tokens})

            full_reply = ''
            input_tokens = 0
            output_tokens = 0
            start_ms = int(_time.time() * 1000)

            async for chunk in test_model.astream(messages):
                if chunk.content:
                    full_reply += chunk.content
                    yield sse_event('token', {'token': chunk.content})
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0

            latency_ms = int(_time.time() * 1000) - start_ms

            # DeepSeek 定价：输入 $0.27/M，输出 $1.10/M，汇率 7.2
            yield sse_event('done', {
                'latencyMs': latency_ms,
                'inputTokens': input_tokens,
                'outputTokens': output_tokens,
                'totalTokens': input_tokens + output_tokens,
                'costCNY': ((input_tokens / 1e6 * 0.27) + (output_tokens / 1e6 * 1.10)) * 7.2,
            })

            logger.info('prompt test done', {'latencyMs': latency_ms, 'inputTokens': input_tokens})
        except Exception as err:
            logger.error('prompt test error', {'error': str(err)})
            yield sse_error(err)

    return EventSourceResponse(event_generator())


@prompt_router.post('/ab-test/stream')
async def prompt_ab_test_stream(req: dict):
    """
    A/B 测试接口（SSE 流式）

    第一步：同一问题，两个 Prompt 分别流式生成回答（真正并行）
    第二步：评估两个回答的质量
    第三步：返回评分结果

    SSE 事件：
    - start: 流开始
    - token_a/token_b: 模型 A/B 的 token
    - done_a/done_b: 模型 A/B 完成
    - scoring: 评分开始
    - eval_done: 评分结果
    - done: 整个流结束
    """
    question = (req.get('question') or '').strip()
    system_prompt_a = req.get('systemPromptA', '')
    system_prompt_b = req.get('systemPromptB', '')
    temperature = req.get('temperature', 0)
    max_tokens = req.get('maxTokens', 800)

    if not question:
        return JSONResponse(status_code=400, content={'error': {'message': '测试问题不能为空'}})

    # 构建消息
    msgs_a = ([SystemMessage(system_prompt_a)] if system_prompt_a else []) + [HumanMessage(question)]
    msgs_b = ([SystemMessage(system_prompt_b)] if system_prompt_b else []) + [HumanMessage(question)]

    # 创建两个独立模型实例（streaming=True）
    model_a = create_chat_model(temperature=temperature, streaming=True)
    model_b = create_chat_model(temperature=temperature, streaming=True)

    queue = asyncio.Queue()
    done_event = asyncio.Event()

    async def stream_side(side, model, messages):
        """流式消费单个模型，token 推入共享 queue"""
        try:
            full_reply, input_tokens, output_tokens = '', 0, 0
            start_ms = int(_time.time() * 1000)
            async for chunk in model.astream(messages):
                if chunk.content:
                    full_reply += chunk.content
                    await queue.put(sse_event(f'token_{side}', {'token': chunk.content}))
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.get('input_tokens', 0) or 0
                    output_tokens = chunk.usage_metadata.get('output_tokens', 0) or 0
            await queue.put(sse_event(f'done_{side}', {
                'latencyMs': int(_time.time() * 1000) - start_ms,
                'inputTokens': input_tokens,
                'outputTokens': output_tokens,
            }))
            return full_reply
        except Exception as err:
            await queue.put(sse_event(f'done_{side}', {'error': str(err)}))
            return ''

    async def run():
        try:
            # 并行流式：两个 astream 同时执行
            answer_a, answer_b = await asyncio.gather(
                stream_side('a', model_a, msgs_a),
                stream_side('b', model_b, msgs_b),
            )
            # 评分阶段
            if answer_a and answer_b:
                await queue.put(sse_event('scoring', {}))
                evaluation = await score_ab_test(question, answer_a, answer_b)
                await queue.put(sse_event('eval_done', evaluation))
        except Exception as err:
            logger.error('ab stream error', {'error': str(err)})
        finally:
            await queue.put(sse_event('done', {}))
            done_event.set()

    asyncio.create_task(run())

    async def event_generator():
        yield sse_event('start', {})
        while not done_event.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except asyncio.TimeoutError:
                continue

    return EventSourceResponse(event_generator())


# ── 模板 CRUD ───────────────────────────────────────────────

@prompt_router.get('/templates')
async def list_prompt_templates():
    """获取所有 Prompt 模板（按创建时间倒序）"""
    return {'templates': list_templates()}


@prompt_router.get('/templates/{template_id}')
async def get_prompt_template(template_id: str):
    """获取指定模板详情"""
    t = get_template(template_id)
    if not t:
        return JSONResponse(status_code=404, content={'error': {'message': '模板不存在'}})
    return t


@prompt_router.post('/templates')
async def create_prompt_template(req: dict):
    """
    创建 Prompt 模板

    参数：name（名称）、systemPrompt（内容）、description（描述）、tags（标签）
    """
    name = (req.get('name') or '').strip()
    system_prompt = (req.get('systemPrompt') or '').strip()
    if not name or not system_prompt:
        return JSONResponse(status_code=400, content={'error': {'message': '模板名称和内容不能为空'}})
    template = save_template(name, system_prompt, req.get('description', ''), req.get('tags', []))
    return {'success': True, 'template': template}


@prompt_router.put('/templates/{template_id}')
async def update_prompt_template(template_id: str, req: dict):
    """更新模板（同时保存历史版本）"""
    template = save_template(
        req.get('name', ''), req.get('systemPrompt', ''),
        req.get('description', ''), req.get('tags', []),
        existing_id=template_id,
    )
    return {'success': True, 'template': template}


@prompt_router.delete('/templates/{template_id}')
async def remove_prompt_template(template_id: str):
    """删除模板（内置模板不可删除）"""
    try:
        delete_template(template_id)
        return {'success': True}
    except ValueError as err:
        return JSONResponse(status_code=400, content={'error': {'message': str(err)}})