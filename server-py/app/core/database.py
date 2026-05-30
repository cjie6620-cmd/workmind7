"""
PostgreSQL 数据库连接模块

使用 SQLAlchemy 异步引擎，支持 pgvector 向量存储
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from ..config import config as app_config


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""
    pass


# 从配置读取数据库 URL
_db_config = app_config.get('database', {})
DB_URL = _db_config.get('url', 'postgresql+asyncpg://ai_love:zx4221335@localhost:5432/ai_love_vector')

# 异步引擎（推荐用于 FastAPI）
async_engine = create_async_engine(
    DB_URL,
    pool_size=_db_config.get('pool_size', 10),
    max_overflow=_db_config.get('max_overflow', 20),
    echo=False,  # 生产环境改为 True 查看 SQL
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

    仅在首次部署时调用，或使用 alembic 进行 migrations
    """
    from ..models.entities import RagChunk, Conversation, ApprovalRecord, AgentConfig, Document, MonitorRecord
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# 表状态缓存，避免每次健康检查都执行 inspect
_tables_status: dict | None = None


async def check_tables() -> dict:
    """
    检查数据库表是否存在，缺失时自动建表

    首次调用时执行检查并缓存结果，后续调用直接返回缓存。
    """
    global _tables_status
    if _tables_status is not None:
        return _tables_status

    from sqlalchemy import inspect as sa_inspect

    # 检测数据库连接和现有表
    try:
        async with async_engine.connect() as conn:
            def _check(sync_conn):
                inspector = sa_inspect(sync_conn)
                return set(inspector.get_table_names())
            existing = await conn.run_sync(_check)
    except Exception as e:
        _tables_status = {"status": "unreachable", "message": f"数据库连接失败: {e}"}
        return _tables_status

    # 导入模型确保 metadata 已注册
    from ..models.entities import RagChunk, Conversation, ApprovalRecord, AgentConfig, Document, MonitorRecord
    required = set(Base.metadata.tables.keys())
    missing = required - existing

    if not missing:
        _tables_status = {"status": "ready", "message": "所有表已就绪"}
        return _tables_status

    # 有缺失表，自动建表
    try:
        await init_db()
        _tables_status = {
            "status": "created",
            "message": f"自动创建了 {len(missing)} 张表",
            "created_tables": sorted(missing)
        }
    except Exception as e:
        _tables_status = {
            "status": "error",
            "message": f"建表失败: {e}",
            "missing_tables": sorted(missing)
        }

    return _tables_status


async def close_db():
    """关闭数据库连接池"""
    await async_engine.dispose()
