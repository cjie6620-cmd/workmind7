"""
初始化 PostgreSQL 数据库和表结构（仅限本地开发/测试库）

使用方法：
    python -m scripts.init_db

注意：本脚本用 create_all 直接建表且不写 alembic_version，
生产/预发布环境一律使用 `alembic upgrade head`（容器 entrypoint 已内置）。
用本脚本初始化的库若要转投迁移管理，需先 `alembic stamp head` 对齐版本。
"""

import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_engine, async_session_factory
from app.models.entities import (
    Base,
    Document,
    RagChunk,
    Conversation,
    ApprovalRecord,
    AgentConfig,
    MonitorRecord,
)


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
    print('  - documents         (知识库文档元信息)')
    print('  - rag_chunks        (RAG 知识库切片)')
    print('  - conversations     (对话历史)')
    print('  - approval_records  (审批记录)')
    print('  - agent_configs     (Agent/工作流配置)')
    print('  - monitor_records   (用量监控记录)')


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