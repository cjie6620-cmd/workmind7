"""
认证路由

- POST /login: 用户名密码登录，返回 access + refresh token
- POST /refresh: 使用 refresh token 换取新 access token

W0b-1b 将接入 users 表与前端 LoginView。
"""

import jwt
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..auth.jwt import (
    TOKEN_TYPE_REFRESH,
    access_token_ttl_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from ..auth.models import LoginRequest, RefreshRequest, TokenResponse
from ..auth.users import AuthStoreUnavailable, authenticate as authenticate_user, get_user_by_id
from ..utils.logger import logger

auth_router = APIRouter()


def _auth_store_unavailable_response(operation: str, error: Exception) -> JSONResponse:
    """记录认证存储故障，并向客户端返回不泄露内部细节的统一响应。"""
    cause = error.__cause__ or error
    logger.error(
        "认证存储不可用",
        {"operation": operation, "errorType": type(cause).__name__},
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "AUTH_STORE_UNAVAILABLE",
                "message": "认证服务暂不可用，请稍后重试",
            }
        },
    )


def _token_response(user_id: str, username: str, role: str) -> dict:
    """构建 token 响应体"""
    access = create_access_token(user_id, username, role)
    refresh = create_refresh_token(user_id, username, role)
    body = TokenResponse(
        accessToken=access,
        refreshToken=refresh,
        expiresIn=access_token_ttl_seconds(),
        role=role,
        userId=user_id,
    )
    return body.model_dump()


@auth_router.post("/login")
async def login(req: LoginRequest):
    """用户名密码登录"""
    try:
        record = await authenticate_user(req.username, req.password)
    except AuthStoreUnavailable as err:
        return _auth_store_unavailable_response("login", err)
    if not record:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}},
        )
    return _token_response(record.user_id, record.username, record.role)


@auth_router.post("/refresh")
async def refresh(req: RefreshRequest):
    """使用 refresh token 换取新的 access + refresh token"""
    try:
        payload = decode_token(req.refreshToken, expected_type=TOKEN_TYPE_REFRESH)
        subject = payload.get("sub")
        if subject is None or not str(subject).strip():
            raise jwt.InvalidTokenError("refresh token 缺少 subject")
        user_id = str(subject)
    except jwt.PyJWTError:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "INVALID_TOKEN", "message": "refresh token 无效或已过期"}},
        )

    try:
        current_user = await get_user_by_id(user_id)
    except Exception as err:
        return _auth_store_unavailable_response("refresh", err)
    if not current_user:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "INVALID_TOKEN", "message": "refresh token 对应用户不存在"}},
        )

    return _token_response(current_user.user_id, current_user.username, current_user.role)
