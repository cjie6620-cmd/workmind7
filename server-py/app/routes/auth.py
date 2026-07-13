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
    payload_to_user,
)
from ..auth.models import LoginRequest, RefreshRequest, TokenResponse
from ..auth.users import authenticate as authenticate_user

auth_router = APIRouter()


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


@auth_router.post('/login')
async def login(req: LoginRequest):
    """用户名密码登录"""
    record = await authenticate_user(req.username, req.password)
    if not record:
        return JSONResponse(
            status_code=401,
            content={'error': {'code': 'INVALID_CREDENTIALS', 'message': '用户名或密码错误'}},
        )
    return _token_response(record.user_id, record.username, record.role)


@auth_router.post('/refresh')
async def refresh(req: RefreshRequest):
    """使用 refresh token 换取新的 access + refresh token"""
    try:
        payload = decode_token(req.refreshToken, expected_type=TOKEN_TYPE_REFRESH)
        user = payload_to_user(payload)
    except jwt.PyJWTError:
        return JSONResponse(
            status_code=401,
            content={'error': {'code': 'INVALID_TOKEN', 'message': 'refresh token 无效或已过期'}},
        )

    return _token_response(user.user_id, user.username, user.role)
