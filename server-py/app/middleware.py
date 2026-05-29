"""
中间件配置模块

包含以下中间件功能：
1. CORS：跨域资源共享配置
2. 限流：令牌桶算法全局限流
3. 请求日志：记录每个请求的方法、路径、状态码、耗时、traceId
4. Prompt 注入检测：防止恶意提示词注入攻击
5. 输入校验：使用 Pydantic 模型验证请求参数

注意：使用纯 ASGI 中间件（StreamingSafeMiddleware）替代 BaseHTTPMiddleware，
避免对流式响应（SSE）的缓冲。
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


# ── 输入校验模型（替代 Zod） ──────────────────────────────────

class ChatRequest(BaseModel):
    """聊天请求参数校验模型"""
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1, max_length=4000)
    sessionId: str = Field(default='default', alias='session_id')
    systemPrompt: str = Field(default='', max_length=2000, alias='system_prompt')
    role: str = 'default'
    userId: str = Field(default='anonymous', alias='user_id')

    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v):
        """校验消息内容非空（去除首尾空格后）"""
        if not v.strip():
            raise ValueError('消息不能为空')
        return v


# ── 令牌桶限流器（全局，与 Node 版一致）──────────────────────

class TokenBucket:
    """
    令牌桶算法限流器

    原理：桶内有一定数量的令牌，每次请求消耗一个令牌，
    令牌按固定速率 refill_rate 补充到桶中。
    """

    def __init__(self, capacity=30, refill_rate=10.0):
        self.capacity = capacity          # 桶容量
        self.refill_rate = refill_rate    # 每秒补充令牌数
        self.tokens = capacity            # 当前令牌数
        self.last_refill = time.time()    # 上次补充时间

    def consume(self):
        """尝试消费一个令牌，返回是否成功"""
        now = time.time()
        elapsed = now - self.last_refill
        # 按时间补充令牌（不超过容量上限）
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


# 全局限流器实例
_bucket = TokenBucket()


# ── Prompt 注入检测 ───────────────────────────────────────────

# 常见 Prompt 注入模式正则表达式
INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?previous\s+instructions?', re.I),    # 忽略之前指令
    re.compile(r'forget\s+(all\s+)?previous', re.I),                  # 忘记之前内容
    re.compile(r'忽略(所有)?之前的指令'),                               # 中文变体
    re.compile(r'你现在是(?!前端|后端|技术|办公)'),                       # 角色扮演注入
    re.compile(r'新的?系统提示'),                                       # 覆盖系统提示
    re.compile(r'act as (?!a helpful)', re.I),                         # 英文角色扮演
]


def check_injection(message: str) -> bool:
    """检测消息是否包含 Prompt 注入特征"""
    return any(p.search(message) for p in INJECTION_PATTERNS)


# ── 中间件注册 ───────────────────────────────────────────────

SSE_PATHS = {
    '/api/chat/stream',
    '/api/agent/run',
    '/api/workflow/start/stream',
    '/api/workflow/resume/stream',
    '/api/erp/submit/stream',
    '/api/prompt/test/stream',
    '/api/knowledge/query/stream',
}


class StreamingSafeMiddleware:
    """
    纯 ASGI 中间件，不会缓冲流式响应。

    替代 BaseHTTPMiddleware（@app.middleware('http')），
    后者的 call_next() 会把整个响应体读进内存，导致 SSE 事件全部缓冲后一次性返回。
    本中间件直接操作 scope/receive/send，对 send 做轻量包装，
    数据直接流向客户端，不经过任何内存缓冲。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')

        # 从请求头提取 traceId
        raw_headers = dict(scope.get('headers', []))
        trace_id = raw_headers.get(b'x-trace-id', str(uuid.uuid4()).encode()).decode()

        # 限流检查
        if not _bucket.consume():
            resp = JSONResponse(
                status_code=429,
                content={'error': {'code': 'RATE_LIMIT', 'message': '请求太频繁，请稍后重试'}},
            )
            await resp(scope, receive, send)
            return

        # SSE 路径：限流 + traceId，直接透传不缓冲
        if path in SSE_PATHS:
            async def send_sse(message):
                if message['type'] == 'http.response.start':
                    headers = list(message.get('headers', []))
                    headers.append((b'x-trace-id', trace_id.encode()))
                    message['headers'] = headers
                await send(message)
            await self.app(scope, receive, send_sse)
            return

        # 普通路径：限流 + traceId + 计时 + 日志
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
        level = 'ERROR' if status_code >= 500 else ('WARN' if status_code >= 400 else 'INFO')
        print(f'[{level}] {method} {path} {status_code} {ms}ms [{trace_id[:8]}]')


def setup_middleware(app: FastAPI):
    """注册所有中间件到 FastAPI 应用"""

    # CORS 中间件：允许指定来源的跨域请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config['app']['allowed_origins'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # 纯 ASGI 中间件：限流 + traceId + 日志（不缓冲流式响应）
    app.add_middleware(StreamingSafeMiddleware)