# 中间件配置：CORS + 请求日志(traceId) + 限流 + 输入校验 + 安全检查
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from .config import config


# ── 输入校验模型（替代 Zod） ──────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(default='default', alias='sessionId')
    system_prompt: str = Field(default='', max_length=2000, alias='systemPrompt')
    role: str = 'default'
    user_id: str = Field(default='anonymous', alias='userId')

    model_config = {'populate_by_name': True}

    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError('消息不能为空')
        return v


# ── 令牌桶限流器（全局，与 Node 版一致）──────────────────────

class TokenBucket:
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


_bucket = TokenBucket()


# ── Prompt 注入检测 ───────────────────────────────────────────

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


# ── 中间件注册 ───────────────────────────────────────────────

def setup_middleware(app: FastAPI):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config['app']['allowed_origins'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.middleware('http')
    async def combined_middleware(request: Request, call_next):
        # 限流
        if not _bucket.consume():
            return JSONResponse(
                status_code=429,
                content={'error': {'code': 'RATE_LIMIT', 'message': '请求太频繁，请稍后重试'}},
            )

        # traceId
        trace_id = request.headers.get('x-trace-id', str(uuid.uuid4()))
        request.state.trace_id = trace_id

        # 请求日志
        start = time.time()
        response = await call_next(request)
        ms = round((time.time() - start) * 1000, 1)

        status = response.status_code
        level = 'ERROR' if status >= 500 else ('WARN' if status >= 400 else 'INFO')
        print(f'[{level}] {request.method} {request.url.path} {status} {ms}ms [{trace_id[:8]}]')

        response.headers['X-Trace-Id'] = trace_id
        return response
