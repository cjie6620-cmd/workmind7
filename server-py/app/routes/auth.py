"""
认证路由

- POST /login: 用户名密码校验（users 表 + bcrypt），签发 access + refresh token
- POST /refresh: 一次性消费旧 jti 轮换新 token 对；重放/已吊销的 jti 返回 401
- POST /logout: 吊销 refresh token 的 jti，幂等（无效 token 也返回成功）

三个端点均在认证白名单中（凭据来自请求体而非 Authorization 头）。
jti 登记/消费依赖 Redis，Redis 不可用时 fail-closed 返回 503。
"""

import uuid

import jwt
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..auth.jwt import (
    TOKEN_TYPE_REFRESH,
    access_token_ttl_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
    refresh_token_ttl_seconds,
)
from ..auth.models import LoginRequest, RefreshRequest, TokenResponse
from ..auth.token_store import consume_refresh_jti, register_refresh_jti, revoke_refresh_jti
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


async def _token_response(user_id: str, username: str, role: str) -> dict:
    """构建 token 响应体，并把新 refresh token 的 jti 登记为有效凭据。"""
    access = create_access_token(user_id, username, role)
    jti = uuid.uuid4().hex
    refresh = create_refresh_token(user_id, username, role, jti)
    # 先登记再返回：登记失败则不签发无法后续轮换的 refresh token。
    await register_refresh_jti(jti, user_id, refresh_token_ttl_seconds())
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
    try:
        return await _token_response(record.user_id, record.username, record.role)
    except Exception as err:
        return _auth_store_unavailable_response("login", err)


@auth_router.post("/refresh")
async def refresh(req: RefreshRequest):
    """使用 refresh token 换取新的 access + refresh token（一次性轮换旧 jti）。"""
    try:
        payload = decode_token(req.refreshToken, expected_type=TOKEN_TYPE_REFRESH)
        subject = payload.get("sub")
        if subject is None or not str(subject).strip():
            raise jwt.InvalidTokenError("refresh token 缺少 subject")
        user_id = str(subject)
        jti = str(payload.get("jti") or "")
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

    # 一次性消费旧 jti：已被轮换/吊销/重放的 token 在此失败。
    try:
        rotated = await consume_refresh_jti(jti, user_id)
    except Exception as err:
        return _auth_store_unavailable_response("refresh", err)
    if not rotated:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "INVALID_TOKEN", "message": "refresh token 已失效，请重新登录"}},
        )

    try:
        return await _token_response(current_user.user_id, current_user.username, current_user.role)
    except Exception as err:
        return _auth_store_unavailable_response("refresh", err)


@auth_router.post("/logout")
async def logout(req: RefreshRequest):
    """服务端登出：吊销该 refresh token 的 jti，使其立即失效（幂等）。"""
    try:
        payload = decode_token(req.refreshToken, expected_type=TOKEN_TYPE_REFRESH)
        jti = str(payload.get("jti") or "")
    except jwt.PyJWTError:
        # 无效/过期 token 无需吊销，登出视为成功（幂等）。
        return {"success": True}
    try:
        await revoke_refresh_jti(jti)
    except Exception as err:
        logger.warning("认证存储登出吊销失败", {"errorType": type(err).__name__})
    return {"success": True}
