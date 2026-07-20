"""FastAPI 认证依赖注入

职责分工：中间件（middleware.py）负责验签并把 UserContext 挂到 request.state；
本模块的 Depends 只做「取用户 + 实时回查 + 角色门禁」。
get_current_user 每次都回查数据库，保证停用/删除/降权即时生效（fail-closed）。
"""

from fastapi import Depends, HTTPException, Request

from .middleware_utils import dev_bypass_user_context, is_auth_enabled
from .models import UserContext
from .users import get_user_by_id


def get_user_from_request(request: Request) -> UserContext | None:
    """从 request.state 读取中间件注入的用户（无则 None）"""
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return None
    if isinstance(user, UserContext):
        return user
    return None


async def get_current_user(request: Request) -> UserContext:
    """
    获取当前登录用户

    AUTH_ENABLED=false 时返回 dev 管理员（便于本地开发）。
    """
    if not is_auth_enabled():
        return dev_bypass_user_context()

    token_user = get_user_from_request(request)
    if token_user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "UNAUTHORIZED", "message": "未认证，请先登录"}},
        )
    # Access token 只证明身份和签发时间；账号停用、删除或降权必须即时生效。
    # 因此权限上下文以数据库当前记录为准，数据库异常时 fail-closed。
    try:
        current_user = await get_user_by_id(token_user.user_id)
    except Exception as err:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "AUTH_STORE_UNAVAILABLE", "message": "认证服务暂不可用"}},
        ) from err
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "UNAUTHORIZED", "message": "账号不存在或已停用"}},
        )
    return UserContext(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
    )


async def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    """要求 admin 角色（已认证但角色不符返回 403）"""
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "需要管理员权限"}},
        )
    return user
