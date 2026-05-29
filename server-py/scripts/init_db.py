"""
初始化 PostgreSQL 数据库和表结构

使用方法：
    python -m scripts.init_db

首次部署时运行，或使用 alembic 进行 migrations
"""

import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_engine, async_session_factory
from app.models.entities import Base, RagChunk, Conversation, ApprovalRecord, AgentConfig


async def init_database():
    """初始化数据库表结构"""
    print('[INFO] 开始初始化数据库...')

    async with async_engine.begin() as conn:
        # 启用 pgvector 扩展
        from sqlalchemy import text
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print('[INFO] pgvector 扩展已启用')

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        print('[INFO] 表结构已创建')

    print('[OK] 数据库初始化完成！')
    print('\n创建的表：')
    print('  - rag_chunks        (RAG 知识库切片)')
    print('  - conversations     (对话历史)')
    print('  - approval_records  (审批记录)')
    print('  - agent_configs    (Agent/工作流配置)')


async def check_connection():
    """检查数据库连接"""
    try:
        async with async_session_factory() as session:
            from sqlalchemy import text
            result = await session.execute(text('SELECT version()'))
            version = result.scalar()
            print(f'[OK] 数据库连接成功')
            print(f'     PostgreSQL 版本: {version[:50]}...')
            return True
    except Exception as e:
        print(f'[ERROR] 数据库连接失败: {e}')
        return False


async def main():
    """主函数"""
    if not await check_connection():
        print('\n请检查 .env 文件中的 DATABASE_URL 配置')
        sys.exit(1)

    await init_database()


if __name__ == '__main__':
    asyncio.run(main())