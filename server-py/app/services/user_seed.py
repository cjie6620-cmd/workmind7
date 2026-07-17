"""启动时种子用户（users 表为空时插入默认账号）"""

import os
import secrets

import bcrypt
from sqlalchemy import select, func

from ..core.database import async_session_factory
from ..models.entities import User


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def ensure_seed_users() -> None:
    """初始化演示账号，并为关闭认证的开发模式保证一个真实 FK owner。"""
    admin_username = os.environ.get("AUTH_ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("AUTH_ADMIN_PASSWORD", "admin123")
    user_username = os.environ.get("AUTH_USER_USERNAME", "user")
    user_password = os.environ.get("AUTH_USER_PASSWORD", "user123")

    async with async_session_factory() as session:
        count = await session.execute(select(func.count()).select_from(User))
        if (count.scalar() or 0) == 0:
            session.add_all(
                [
                    User(
                        id="admin", username=admin_username, password_hash=_hash_password(admin_password), role="admin"
                    ),
                    User(id="user", username=user_username, password_hash=_hash_password(user_password), role="user"),
                ]
            )

        # AUTH_ENABLED=false 的请求使用 user_id=dev。该记录必须真实存在，
        # 否则 documents.owner_user_id 等外键写入会在本地标准链路中失败。
        auth_enabled = os.environ.get("AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}
        if not auth_enabled:
            existing_dev = await session.execute(select(User.id).where(User.id == "dev"))
            if existing_dev.scalar_one_or_none() is None:
                session.add(
                    User(
                        id="dev",
                        username=f"dev-bypass-{secrets.token_hex(4)}",
                        password_hash=_hash_password(secrets.token_urlsafe(32)),
                        role="admin",
                        is_active=True,
                    )
                )
        await session.commit()
