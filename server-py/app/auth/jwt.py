"""JWT 签发与校验

令牌模型：
- access token：短命、纯无状态，每个请求仅验签（get_current_user 另做数据库回查）
- refresh token：长命、服务端有状态——携带 jti，签发时登记到 Redis
  （见 token_store），刷新时一次性消费实现轮换，登出时吊销
两类 token 用 payload 的 type 字段区分，decode_token 按 expected_type 校验。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import config
from .models import UserContext

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def _auth_cfg() -> dict:
    return config["auth"]


def _secret() -> str:
    return _auth_cfg()["jwt_secret"]


def _algorithm() -> str:
    return _auth_cfg().get("jwt_algorithm", "HS256")


def create_access_token(user_id: str, username: str, role: str) -> str:
    """签发 access token"""
    hours = _auth_cfg()["jwt_expire_hours"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(hours=hours),
    }
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def create_refresh_token(user_id: str, username: str, role: str, jti: str) -> str:
    """签发 refresh token；jti 用于服务端一次性轮换与吊销。"""
    days = _auth_cfg()["jwt_refresh_expire_days"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": TOKEN_TYPE_REFRESH,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=days),
    }
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """
    解码并校验 JWT

    expected_type: access / refresh；None 表示不校验 type
    """
    payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"期望 token 类型 {expected_type}")
    return payload


def payload_to_user(payload: dict[str, Any]) -> UserContext:
    """JWT payload → UserContext"""
    return UserContext(
        user_id=str(payload["sub"]),
        username=str(payload.get("username", payload["sub"])),
        role=str(payload.get("role", "user")),
    )


def access_token_ttl_seconds() -> int:
    """access token 有效期（秒）"""
    return int(_auth_cfg()["jwt_expire_hours"]) * 3600


def refresh_token_ttl_seconds() -> int:
    """refresh token 有效期（秒），用于 jti 在 Redis 中的存活时间。"""
    return int(_auth_cfg()["jwt_refresh_expire_days"]) * 86400
