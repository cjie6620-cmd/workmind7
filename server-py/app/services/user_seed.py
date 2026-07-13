"""启动时种子用户（users 表为空时插入默认账号）"""

import os

import bcrypt
from sqlalchemy import select, func

from ..core.database import async_session_factory
from ..models.entities import User


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


async def ensure_seed_users() -> None:
    """users 表为空时插入 admin + user 默认账号"""
    admin_username = os.environ.get('AUTH_ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('AUTH_ADMIN_PASSWORD', 'admin123')
    user_username = os.environ.get('AUTH_USER_USERNAME', 'user')
    user_password = os.environ.get('AUTH_USER_PASSWORD', 'user123')

    async with async_session_factory() as session:
        count = await session.execute(select(func.count()).select_from(User))
        if (count.scalar() or 0) > 0:
            return

        session.add_all([
            User(id='admin', username=admin_username, password_hash=_hash_password(admin_password), role='admin'),
            User(id='user', username=user_username, password_hash=_hash_password(user_password), role='user'),
        ])
        await session.commit()
