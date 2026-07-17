"""
用户凭据校验

users 表是启用认证后的唯一身份来源；环境变量账号只用于应用启动时写入种子用户。
"""

from dataclasses import dataclass

import bcrypt
from sqlalchemy import select

from ..core.database import async_session_factory
from ..models.entities import User


@dataclass(frozen=True)
class StoredUser:
    """内存中的用户记录"""

    user_id: str
    username: str
    password: str
    role: str


class AuthStoreUnavailable(RuntimeError):
    """认证数据库不可用，调用方应返回 503 而不是误报凭据无效。"""


def _verify_password(plain: str, password_hash: str) -> bool:
    """校验明文密码与 bcrypt 哈希"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


async def authenticate_db(username: str, password: str) -> StoredUser | None:
    """从数据库校验用户名密码"""
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == username, User.is_active.is_(True)))
        row = result.scalar_one_or_none()
        if not row or not _verify_password(password, row.password_hash):
            return None
        return StoredUser(
            user_id=row.id,
            username=row.username,
            password="",
            role=row.role,
        )


async def get_user_by_id(user_id: str) -> StoredUser | None:
    """按 JWT subject 回查当前数据库用户及其最新角色。"""
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        row = result.scalar_one_or_none()
        if not row:
            return None
        return StoredUser(
            user_id=row.id,
            username=row.username,
            password="",
            role=row.role,
        )


async def authenticate(username: str, password: str) -> StoredUser | None:
    """使用数据库校验凭据；认证存储异常时显式失败。"""
    try:
        return await authenticate_db(username, password)
    except Exception as err:
        raise AuthStoreUnavailable("认证存储不可用") from err


def get_dev_bypass_user() -> StoredUser:
    """AUTH_ENABLED=false 时使用的占位用户"""
    return StoredUser(
        user_id="dev",
        username="dev",
        password="",
        role="admin",
    )
