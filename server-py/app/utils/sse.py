"""SSE 事件构造（基于 sse-starlette）

全站 SSE 契约：每个流必须以显式终态事件结束（done 或 error），
前端据此驱动状态机，禁止依赖连接关闭猜测结果。
错误事件只携带 classify_error 产出的安全文案，原始异常细节仅进日志。
"""

from sse_starlette.event import JSONServerSentEvent

from .errors import classify_error


def sse_event(event: str, data: dict) -> JSONServerSentEvent:
    """构造 SSE 事件（替代手写 f'event: ...\ndata: ...\n\n'）"""
    return JSONServerSentEvent(event=event, data=data)


def sse_error(err) -> JSONServerSentEvent:
    """构造 SSE 错误事件"""
    app_err = classify_error(err)
    return JSONServerSentEvent(
        event="error",
        data={"message": app_err.user_message, "retryable": app_err.retryable},
    )
