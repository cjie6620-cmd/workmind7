"""
中间件层

单个纯 ASGI 中间件（StreamingSafeMiddleware）按序完成：
JWT 认证 → 分布式限流 → trace_id 与安全响应头注入 → 请求日志。
不用 BaseHTTPMiddleware 是因为它会缓冲响应体，破坏 SSE 流式输出。
另提供 Prompt 注入检测 check_injection 供 chat/agent/knowledge 入口复用。
中间件注册顺序见 setup_middleware 的说明。
"""

import asyncio
import os
import re
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import config
from .auth.middleware_utils import is_auth_enabled, is_public_api_path, resolve_auth_user
from .utils.logger import logger
from .utils.responses import error_response

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"forget\s+(all\s+)?previous", re.I),
    re.compile(r"忽略(所有)?之前的指令"),
    re.compile(r"你现在是(?!前端|后端|技术|办公)"),
    re.compile(r"新的?系统提示"),
    re.compile(r"act as (?!a helpful)", re.I),
]


def check_injection(message: str) -> bool:
    """规则版 Prompt 注入检测（第一道防线；最终防线是工具权限与 owner 隔离）"""
    return any(p.search(message) for p in INJECTION_PATTERNS)


SSE_PATHS = {
    "/api/chat/stream",
    "/api/agent/run",
    "/api/workflow/start/stream",
    "/api/workflow/resume/stream",
    "/api/erp/submit/stream",
    "/api/prompt/test/stream",
    "/api/prompt/ab-test/stream",
    "/api/knowledge/query/stream",
}

# 昂贵接口限流更严
STRICT_RATE_PATHS = {
    "/api/agent/run",
    "/api/knowledge/query/stream",
    "/api/chat/stream",
}

DEFAULT_RATE_LIMIT = 30
STRICT_RATE_LIMIT = 10
RATE_WINDOW_SEC = 60


def _rate_limit_key(scope: Scope, path: str) -> str:
    """按 userId（已认证）或 IP 维度限流"""
    state = scope.get("state", {})
    auth_user = state.get("auth_user")
    if auth_user and hasattr(auth_user, "user_id"):
        return f"rate:user:{auth_user.user_id}:{path}"
    client = scope.get("client")
    ip = client[0] if client else "unknown"
    return f"rate:ip:{ip}:{path}"


def _rate_limit_incr(key: str) -> int:
    """固定窗口计数：仅在窗口首个请求设置 TTL，让窗口能自然过期。

    ❌ 每次请求都 EXPIRE 会让活跃用户的计数键永不过期、累积后被长期误封。
    ✅ 只在 INCR 结果为 1（窗口首个请求）时设置一次 TTL。
    """
    from .core.redis_client import get_redis

    r = get_redis()
    count = r.incr(key)
    if count == 1:
        r.expire(key, RATE_WINDOW_SEC)
    return int(count)


async def _check_rate_limit(scope: Scope, path: str) -> bool:
    """固定窗口限流；同步 redis-py 放线程池，避免阻塞事件循环。"""
    limit = STRICT_RATE_LIMIT if path in STRICT_RATE_PATHS else DEFAULT_RATE_LIMIT
    key = _rate_limit_key(scope, path)

    try:
        count = await asyncio.to_thread(_rate_limit_incr, key)
        return count <= limit
    except Exception:
        # 生产昂贵路径 fail-closed；测试环境保留进程内回退，避免无 Redis 时整仓集成不可用。
        if path in STRICT_RATE_PATHS and os.environ.get("TESTING") != "1":
            logger.warning("rate limit redis unavailable; denying expensive path", {"path": path})
            return False
        return _fallback_bucket.consume()


class TokenBucket:
    """进程内令牌桶：Redis 不可用时非昂贵路径的限流回退（单进程近似值）"""

    def __init__(self, capacity=30, refill_rate=10.0):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self):
        """按流逝时间补充令牌后尝试消费一枚；无令牌返回 False（应拒绝请求）"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


_fallback_bucket = TokenBucket()

# 安全响应头（纵深防御）：防 MIME 嗅探、点击劫持、referrer 泄露；生产追加 HSTS。
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]
if config["app"]["env"] == "production":
    _SECURITY_HEADERS.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))


def _append_security_headers(headers: list) -> None:
    """向响应头追加安全头（已存在的同名头不覆盖，尊重路由显式设置）。"""
    existing = {name.lower() for name, _ in headers}
    for name, value in _SECURITY_HEADERS:
        if name not in existing:
            headers.append((name, value))


class StreamingSafeMiddleware:
    """纯 ASGI 中间件，不缓冲流式响应"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        """请求处理顺序：认证（公共路径豁免）→ 限流（健康探针豁免）→
        SSE 路径只注头不计时（避免长连接日志失真）→ 普通路径注头 + 访问日志。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        raw_headers = dict(scope.get("headers", []))
        trace_id = raw_headers.get(b"x-trace-id", str(uuid.uuid4()).encode()).decode()

        if path.startswith("/api/") and not is_public_api_path(path, method):
            auth_user = resolve_auth_user(scope)
            if auth_user is None:
                resp = error_response(401, "未认证，请先登录", code="UNAUTHORIZED")
                await resp(scope, receive, send)
                return
            state = scope.setdefault("state", {})
            state["auth_user"] = auth_user
        elif is_auth_enabled():
            auth_user = resolve_auth_user(scope)
            if auth_user is not None:
                state = scope.setdefault("state", {})
                state["auth_user"] = auth_user

        # 健康探针必须豁免限流：Docker/K8s 高频探活，否则会把容器打成 unhealthy（T2）
        if not path.startswith("/health") and not await _check_rate_limit(scope, path):
            resp = error_response(429, "请求太频繁，请稍后重试", code="RATE_LIMIT")
            await resp(scope, receive, send)
            return

        if path in SSE_PATHS:

            async def send_sse(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-trace-id", trace_id.encode()))
                    _append_security_headers(headers)
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_sse)
            return

        start = time.perf_counter()
        status_code = 0

        async def send_with_log(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", trace_id.encode()))
                _append_security_headers(headers)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_log)

        ms = round((time.perf_counter() - start) * 1000, 1)
        method = scope.get("method", "?")
        level_name = "error" if status_code >= 500 else ("warning" if status_code >= 400 else "info")
        log_fn = getattr(logger, level_name, logger.info)
        log_fn(f"{method} {path} {status_code} {ms}ms trace={trace_id[:8]}")


def setup_middleware(app: FastAPI):
    """注册所有中间件。

    Starlette 中「后添加者更外层」。先加 StreamingSafeMiddleware、后加 CORS，
    使 CORS 成为最外层：这样 StreamingSafe 短路的 401/429 响应也会经过 CORS 补上跨域头，
    浏览器才能读到错误体（否则前端只会看到网络错误，无法区分未登录/被限流）。
    """
    app.add_middleware(StreamingSafeMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config["app"]["allowed_origins"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Trace-Id", "X-API-Key"],
    )
