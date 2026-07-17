"""SSE 工具模块：基于 sse-starlette 封装事件构造"""

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
