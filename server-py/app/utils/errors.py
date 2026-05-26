# 统一错误处理：错误分类、用户友好提示
import json


class AppError(Exception):
    def __init__(self, message, code='UNKNOWN', status_code=500, retryable=False, user_message=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.user_message = user_message or '服务暂时不可用，请稍后重试'


def classify_error(err):
    if isinstance(err, AppError):
        return err

    msg = str(err)
    status = getattr(err, 'status_code', None) or getattr(err, 'status', None)

    if status == 429:
        return AppError('API 限流', code='RATE_LIMIT', status_code=429, retryable=True,
                        user_message='请求太频繁，请稍后重试')
    if status in (401, 403):
        return AppError('认证失败', code='AUTH_ERROR', status_code=500, retryable=False,
                        user_message='服务配置错误，请联系管理员')
    if (status and status >= 500) or 'ECONNRESET' in msg:
        return AppError('服务不可用', code='SERVICE_ERROR', status_code=503, retryable=True,
                        user_message='服务暂时不可用，请稍后重试')
    if 'timeout' in msg.lower():
        return AppError('请求超时', code='TIMEOUT', status_code=504, retryable=True,
                        user_message='响应超时，请重试')
    return AppError(msg, code='UNKNOWN', retryable=False)


def send_sse_error(err):
    """生成 SSE 格式的错误事件字符串"""
    app_err = classify_error(err)
    data = json.dumps({'message': app_err.user_message, 'retryable': app_err.retryable}, ensure_ascii=False)
    return f'event: error\ndata: {data}\n\n'
