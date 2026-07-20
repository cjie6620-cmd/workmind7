"""ASGI 中间件认证工具函数（在纯 ASGI 层运行，不依赖 FastAPI 依赖注入）"""

import jwt
from starlette.types import Scope

from ..config import config
from .jwt import TOKEN_TYPE_ACCESS, decode_token, payload_to_user
from .models import UserContext
from .users import get_dev_bypass_user


def is_auth_enabled() -> bool:
    """是否启用 JWT 认证（中间件与 Depends 共用的唯一开关判断）"""
    return bool(config["auth"]["enabled"])


def is_public_api_path(path: str, method: str) -> bool:
    """无需 Bearer token 的路径白名单。

    - OPTIONS：CORS 预检请求不带 Authorization
    - /health*：容器探针高频访问，且不能因认证配置故障而误报不健康
    - /auth/login：登录本身无凭据
    - /auth/refresh、/auth/logout：凭据是请求体里的 refresh token，而非 access token
      （access 过期后仍需能刷新/登出）
    """
    if method == "OPTIONS":
        return True
    if path.startswith("/health"):
        return True
    if path in ("/api/auth/login", "/api/auth/refresh", "/api/auth/logout"):
        return True
    return False


def extract_bearer_token(scope: Scope) -> str | None:
    """从 ASGI scope 提取 Bearer token"""
    raw_headers = dict(scope.get("headers", []))
    auth_header = raw_headers.get(b"authorization", b"").decode()
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    return token or None


def dev_bypass_user_context() -> UserContext:
    """AUTH_ENABLED=false 时的占位管理员上下文（dev 用户由种子数据保证 FK 存在）"""
    bypass = get_dev_bypass_user()
    return UserContext(
        user_id=bypass.user_id,
        username=bypass.username,
        role=bypass.role,
    )


def resolve_auth_user(scope: Scope) -> UserContext | None:
    """
    解析当前请求用户

    AUTH_ENABLED=false → dev 用户；否则校验 access JWT。
    """
    if not is_auth_enabled():
        return dev_bypass_user_context()

    token = extract_bearer_token(scope)
    if not token:
        return None

    try:
        payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
        return payload_to_user(payload)
    except jwt.PyJWTError:
        return None
