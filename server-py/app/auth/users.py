"""
用户凭据校验

优先从 users 表查询（bcrypt）；表为空或查询失败时回退到环境变量开发账号。
"""

import os
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


def _load_dev_users() -> dict[str, StoredUser]:
    """从环境变量加载开发账号（username → StoredUser）"""
    admin_user = os.environ.get('AUTH_ADMIN_USERNAME', 'admin')
    admin_pass = os.environ.get('AUTH_ADMIN_PASSWORD', 'admin123')
    normal_user = os.environ.get('AUTH_USER_USERNAME', 'user')
    normal_pass = os.environ.get('AUTH_USER_PASSWORD', 'user123')

    return {
        admin_user: StoredUser(
            user_id='admin',
            username=admin_user,
            password=admin_pass,
            role='admin',
        ),
        normal_user: StoredUser(
            user_id='user',
            username=normal_user,
            password=normal_pass,
            role='user',
        ),
    }


def _verify_password(plain: str, password_hash: str) -> bool:
    """校验明文密码与 bcrypt 哈希"""
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), password_hash.encode('utf-8'))
    except ValueError:
        return False


async def authenticate_db(username: str, password: str) -> StoredUser | None:
    """从数据库校验用户名密码"""
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        row = result.scalar_one_or_none()
        if not row or not _verify_password(password, row.password_hash):
            return None
        return StoredUser(
            user_id=row.id,
            username=row.username,
            password='',
            role=row.role,
        )


def authenticate_env(username: str, password: str) -> StoredUser | None:
    """从环境变量校验（测试/回退）"""
    users = _load_dev_users()
    record = users.get(username)
    if not record or record.password != password:
        return None
    return record


async def authenticate(username: str, password: str) -> StoredUser | None:
    """校验用户名密码，成功返回用户记录"""
    from ..config import config

    is_production = config['app']['env'] == 'production'

    # 第一步：尝试数据库
    try:
        db_user = await authenticate_db(username, password)
        if db_user:
            return db_user
    except Exception:
        if is_production:
            return None

    # 第二步：非生产环境回退环境变量账号
    if is_production:
        return None
    return authenticate_env(username, password)


def get_dev_bypass_user() -> StoredUser:
    """AUTH_ENABLED=false 时使用的占位用户"""
    return StoredUser(
        user_id='dev',
        username='dev',
        password='',
        role='admin',
    )
