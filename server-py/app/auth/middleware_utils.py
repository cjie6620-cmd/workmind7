"""ASGI 中间件认证工具函数"""

import jwt
from starlette.types import Scope

from ..config import config
from .jwt import TOKEN_TYPE_ACCESS, decode_token, payload_to_user
from .models import UserContext
from .users import get_dev_bypass_user


def is_auth_enabled() -> bool:
    return bool(config['auth']['enabled'])


def is_public_api_path(path: str, method: str) -> bool:
    """无需 Bearer token 的 API 路径"""
    if method == 'OPTIONS':
        return True
    if path.startswith('/health'):
        return True
    if path == '/api/auth/login':
        return True
    if path == '/api/auth/refresh':
        return True
    return False


def extract_bearer_token(scope: Scope) -> str | None:
    """从 ASGI scope 提取 Bearer token"""
    raw_headers = dict(scope.get('headers', []))
    auth_header = raw_headers.get(b'authorization', b'').decode()
    if not auth_header.lower().startswith('bearer '):
        return None
    token = auth_header[7:].strip()
    return token or None


def resolve_auth_user(scope: Scope) -> UserContext | None:
    """
    解析当前请求用户

    AUTH_ENABLED=false → dev 用户；否则校验 access JWT。
    """
    if not is_auth_enabled():
        bypass = get_dev_bypass_user()
        return UserContext(
            user_id=bypass.user_id,
            username=bypass.username,
            role=bypass.role,
        )

    token = extract_bearer_token(scope)
    if not token:
        return None

    try:
        payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
        return payload_to_user(payload)
    except jwt.PyJWTError:
        return None
