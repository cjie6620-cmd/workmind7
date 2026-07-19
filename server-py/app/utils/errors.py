"""
错误处理模块

提供统一的错误分类和 SSE 错误格式化：
1. AppError: 应用层异常类
2. classify_error: 根据异常类型分类
3. send_sse_error: 生成 SSE 格式的错误事件

错误分类：
- RATE_LIMIT: API 限流
- AUTH_ERROR: 认证失败
- SERVICE_ERROR: 服务不可用
- TIMEOUT: 请求超时
- UNKNOWN: 未知错误
"""


class AppError(Exception):
    """
    应用层异常

    参数：
    - message: 错误消息
    - code: 错误代码
    - status_code: HTTP 状态码
    - retryable: 是否可重试
    - user_message: 用户友好的错误提示
    """

    def __init__(self, message, code="UNKNOWN", status_code=500, retryable=False, user_message=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.user_message = user_message or "服务暂时不可用，请稍后重试"


def classify_error(err):
    """
    错误分类

    根据异常类型或状态码，返回标准化的 AppError

    规则：
    - 已经是 AppError：直接返回
    - HTTP 429：限流错误
    - HTTP 401/403：认证失败
    - HTTP 5xx 或连接断开：服务不可用
    - 超时关键词：请求超时
    - 其他：未知错误
    """
    if isinstance(err, AppError):
        return err

    msg = str(err)
    # 尝试从异常对象获取状态码
    status = getattr(err, "status_code", None) or getattr(err, "status", None)

    if status == 402:
        return AppError(
            "预算超限",
            code="BUDGET_EXCEEDED",
            status_code=402,
            retryable=False,
            user_message="今日 AI 用量已达上限，请稍后再试或联系管理员",
        )
    if status == 429:
        return AppError(
            "API 限流", code="RATE_LIMIT", status_code=429, retryable=True, user_message="请求太频繁，请稍后重试"
        )
    if status in (401, 403):
        return AppError(
            "认证失败", code="AUTH_ERROR", status_code=500, retryable=False, user_message="服务配置错误，请联系管理员"
        )
    if (status and status >= 500) or "ECONNRESET" in msg:
        return AppError(
            "服务不可用",
            code="SERVICE_ERROR",
            status_code=503,
            retryable=True,
            user_message="服务暂时不可用，请稍后重试",
        )
    if "timeout" in msg.lower():
        return AppError("请求超时", code="TIMEOUT", status_code=504, retryable=True, user_message="响应超时，请重试")
    return AppError(msg, code="UNKNOWN", retryable=False)


def send_sse_error(err):
    """
    生成 SSE 格式的错误事件（已废弃，请使用 sse.utils.sse.sse_error）

    保留此函数仅为向后兼容，新代码请用 sse_error()
    """
    from .sse import sse_error

    return sse_error(err)
