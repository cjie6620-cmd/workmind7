"""
PostgreSQL 数据库连接模块

使用 SQLAlchemy 异步引擎，支持 pgvector 向量存储
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

# 异步引擎（推荐用于 FastAPI）
# 测试环境使用 NullPool，避免 asyncpg 连接复用导致 "another operation is in progress"
_engine_kwargs: dict = {
    "pool_size": _db_config.get("pool_size", 10),
    "max_overflow": _db_config.get("max_overflow", 20),
    "echo": False,
}
if os.environ.get("TESTING") == "1":
    _engine_kwargs = {"poolclass": NullPool, "echo": False}

async_engine = create_async_engine(
    DB_URL,
    **_engine_kwargs,
)

# 异步 Session Factory
async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入获取数据库会话

    用法:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    上下文管理器方式获取数据库会话

    用法:
        async with get_db_context() as db:
            result = await db.execute(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """
    初始化数据库表结构

    开发专用；生产环境请使用 alembic upgrade head
    """
    _register_models()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_tables_status() -> dict:
    """
    检查数据库表是否存在（不自动建表）
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


async def check_tables() -> dict:
    """兼容旧调用：仅检查状态，不自动建表"""
    return await check_tables_status()


async def close_db():
    """关闭数据库连接池"""
    await async_engine.dispose()
