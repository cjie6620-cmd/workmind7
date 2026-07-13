"""
初始化默认用户账号

使用方法：
    cd server-py && uv run python -m scripts.seed_users

默认账号（可通过环境变量覆盖密码）：
    admin / admin123  (admin)
    user  / user123   (user)
"""

import asyncio
import os
import sys

import bcrypt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import async_session_factory, async_engine
from app.models.entities import Base, User


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


async def seed_users() -> None:
    """插入 admin + user 测试账号（已存在则跳过）"""
    admin_username = os.environ.get('AUTH_ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('AUTH_ADMIN_PASSWORD', 'admin123')
    user_username = os.environ.get('AUTH_USER_USERNAME', 'user')
    user_password = os.environ.get('AUTH_USER_PASSWORD', 'user123')

    seeds = [
        ('admin', admin_username, admin_password, 'admin'),
        ('user', user_username, user_password, 'user'),
    ]

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        for user_id, username, password, role in seeds:
            existing = await session.execute(select(User).where(User.username == username))
            if existing.scalar_one_or_none():
                print(f'[SKIP] 用户已存在: {username}')
                continue
            session.add(User(
                id=user_id,
                username=username,
                password_hash=_hash_password(password),
                role=role,
            ))
            print(f'[OK] 创建用户: {username} ({role})')
        await session.commit()

    print('[OK] 用户种子数据完成')


if __name__ == '__main__':
    asyncio.run(seed_users())
