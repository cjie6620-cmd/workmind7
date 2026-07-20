"""
PostgreSQL 连接层（SQLAlchemy 2.0 async + asyncpg，含 pgvector）

对外暴露：
- Base / async_engine / async_session_factory：ORM 基类与全局引擎、会话工厂。
  业务层统一 `async with async_session_factory() as session` 取会话；
  `expire_on_commit=False` 防止 commit 后属性访问触发同步 IO（MissingGreenlet）。
- get_db_context：需要「成功即 commit、异常即 rollback」语义时的上下文封装。
- check_tables_status：只读校验表结构是否就绪（启动与健康检查用，不自动建表）。
- close_db：应用退出时释放连接池。

表结构变更一律走 alembic 迁移（docker-entrypoint.sh 启动时执行 upgrade head）；
开发建表脚本见 scripts/init_db.py。
"""

import os
from contextlib import asynccontextmanager
from importlib import import_module
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from ..config import config as app_config


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""

    pass


def _register_models() -> None:
    """导入实体模块，使所有 ORM 表注册到 ``Base.metadata``。"""
    import_module("..models.entities", package=__package__)


# 从配置读取数据库 URL（唯一来源，无 fallback）
_db_config = app_config.get("database", {})
DB_URL = _db_config.get("url")
if not DB_URL:
    raise RuntimeError("DATABASE_URL 未配置，请在 .env 中设置")

# 测试环境使用 NullPool，避免 asyncpg 连接复用导致 "another operation is in progress"
_engine_kwargs: dict = {
    "pool_size": _db_config.get("pool_size", 10),
    "max_overflow": _db_config.get("max_overflow", 20),
    # 取连接前 ping，剔除 DB 重启/空闲断连后的失效连接，避免突发 500
    "pool_pre_ping": True,
    # 定期回收长寿命连接，防止被 DB/LB 超时静默关闭
    "pool_recycle": _db_config.get("pool_recycle", 1800),
    "pool_timeout": _db_config.get("pool_timeout", 30),
    "echo": False,
}
if os.environ.get("TESTING") == "1":
    _engine_kwargs = {"poolclass": NullPool, "echo": False}

async_engine = create_async_engine(
    DB_URL,
    **_engine_kwargs,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """带事务语义的会话上下文：正常退出自动 commit，异常自动 rollback。

    用法:
        async with get_db_context() as db:
            db.add(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_tables_status() -> dict:
    """只读检查 ORM 声明的表是否都已存在（不自动建表）。

    返回 status ∈ {ready, missing_tables, unreachable}，供启动 fail-fast
    与 /health 就绪探针共用。
    """
    from sqlalchemy import inspect as sa_inspect

    try:
        async with async_engine.connect() as conn:

            def _check(sync_conn):
                inspector = sa_inspect(sync_conn)
                return set(inspector.get_table_names())

            existing = await conn.run_sync(_check)
    except Exception as e:
        return {"status": "unreachable", "message": f"数据库连接失败: {e}"}

    _register_models()
    required = set(Base.metadata.tables.keys())
    missing = required - existing

    if not missing:
        return {"status": "ready", "message": "所有表已就绪"}

    return {
        "status": "missing_tables",
        "message": f"缺少 {len(missing)} 张表，请运行 alembic upgrade head",
        "missing_tables": sorted(missing),
    }


async def close_db():
    """关闭数据库连接池（应用退出时由 lifespan 调用）"""
    await async_engine.dispose()
