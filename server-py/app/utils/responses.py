"""统一 JSON 错误响应构造

全站错误契约：{"error": {"code"?: str, "message": str}}。
路由/中间件禁止手写错误体，一律经 error_response 构造，
保证前端 `err.response.data.error.message` 的解析路径永远成立。
"""

from fastapi.responses import JSONResponse


def error_response(status_code: int, message: str, code: str | None = None) -> JSONResponse:
    """构造标准错误响应；code 仅在需要程序化区分错误类型时携带。"""
    error: dict[str, str] = {}
    if code:
        error["code"] = code
    error["message"] = message
    return JSONResponse(status_code=status_code, content={"error": error})
