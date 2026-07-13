"""
中间件配置模块

包含：CORS、Redis 分布式限流、请求日志、JWT 认证、Prompt 注入检测
"""

import re
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import config
from .auth.middleware_utils import is_auth_enabled, is_public_api_path, resolve_auth_user
from .utils.logger import logger


class ChatRequest(BaseModel):
    """聊天请求参数校验模型"""
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1, max_length=4000)
    sessionId: str = Field(default='default', alias='session_id')
    systemPrompt: str = Field(default='', max_length=2000, alias='system_prompt')
    role: str = 'default'

    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError('消息不能为空')
        return v


INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?previous\s+instructions?', re.I),
    re.compile(r'forget\s+(all\s+)?previous', re.I),
    re.compile(r'忽略(所有)?之前的指令'),
    re.compile(r'你现在是(?!前端|后端|技术|办公)'),
    re.compile(r'新的?系统提示'),
    re.compile(r'act as (?!a helpful)', re.I),
]


def check_injection(message: str) -> bool:
    return any(p.search(message) for p in INJECTION_PATTERNS)


SSE_PATHS = {
    '/api/chat/stream',
    '/api/agent/run',
    '/api/workflow/start/stream',
    '/api/workflow/resume/stream',
    '/api/erp/submit/stream',
    '/api/prompt/test/stream',
    '/api/prompt/ab-test/stream',
    '/api/knowledge/query/stream',
}

# 昂贵接口限流更严
STRICT_RATE_PATHS = {
    '/api/agent/run',
    '/api/knowledge/query/stream',
    '/api/chat/stream',
}

DEFAULT_RATE_LIMIT = 30
STRICT_RATE_LIMIT = 10
RATE_WINDOW_SEC = 60


def _rate_limit_key(scope: Scope, path: str) -> str:
    """按 userId（已认证）或 IP 维度限流"""
    state = scope.get('state', {})
    auth_user = state.get('auth_user')
    if auth_user and hasattr(auth_user, 'user_id'):
        return f'rate:user:{auth_user.user_id}:{path}'
    client = scope.get('client')
    ip = client[0] if client else 'unknown'
    return f'rate:ip:{ip}:{path}'


def _check_rate_limit(scope: Scope, path: str) -> bool:
    """Redis 滑动窗口限流，失败时回退允许通过"""
    limit = STRICT_RATE_LIMIT if path in STRICT_RATE_PATHS else DEFAULT_RATE_LIMIT
    key = _rate_limit_key(scope, path)

    try:
        from .core.redis_client import get_redis
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, RATE_WINDOW_SEC)
        count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:
        return _fallback_bucket.consume()


class TokenBucket:
    """进程内限流回退"""

    def __init__(self, capacity=30, refill_rate=10.0):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def consume(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


_fallback_bucket = TokenBucket()


class StreamingSafeMiddleware:
    """纯 ASGI 中间件，不缓冲流式响应"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')
        method = scope.get('method', 'GET')

        raw_headers = dict(scope.get('headers', []))
        trace_id = raw_headers.get(b'x-trace-id', str(uuid.uuid4()).encode()).decode()

        if path.startswith('/api/') and not is_public_api_path(path, method):
            auth_user = resolve_auth_user(scope)
            if auth_user is None:
                resp = JSONResponse(
                    status_code=401,
                    content={'error': {'code': 'UNAUTHORIZED', 'message': '未认证，请先登录'}},
                )
                await resp(scope, receive, send)
                return
            state = scope.setdefault('state', {})
            state['auth_user'] = auth_user
        elif is_auth_enabled():
            auth_user = resolve_auth_user(scope)
            if auth_user is not None:
                state = scope.setdefault('state', {})
                state['auth_user'] = auth_user

        if not _check_rate_limit(scope, path):
            resp = JSONResponse(
                status_code=429,
                content={'error': {'code': 'RATE_LIMIT', 'message': '请求太频繁，请稍后重试'}},
            )
            await resp(scope, receive, send)
            return

        if path in SSE_PATHS:
            async def send_sse(message):
                if message['type'] == 'http.response.start':
                    headers = list(message.get('headers', []))
                    headers.append((b'x-trace-id', trace_id.encode()))
                    message['headers'] = headers
                await send(message)
            await self.app(scope, receive, send_sse)
            return

        start = time.time()
        status_code = 0

        async def send_with_log(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message.get('status', 0)
                headers = list(message.get('headers', []))
                headers.append((b'x-trace-id', trace_id.encode()))
                message['headers'] = headers
            await send(message)

        await self.app(scope, receive, send_with_log)

        ms = round((time.time() - start) * 1000, 1)
        method = scope.get('method', '?')
        level_name = 'error' if status_code >= 500 else ('warning' if status_code >= 400 else 'info')
        log_fn = getattr(logger, level_name, logger.info)
        log_fn(f'{method} {path} {status_code} {ms}ms trace={trace_id[:8]}')


def setup_middleware(app: FastAPI):
    """注册所有中间件"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config['app']['allowed_origins'],
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allow_headers=['Content-Type', 'Authorization', 'X-Trace-Id', 'X-API-Key'],
    )
    app.add_middleware(StreamingSafeMiddleware)
