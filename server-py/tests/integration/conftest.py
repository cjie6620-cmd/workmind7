"""集成测试专用 fixtures：隔离 DB 连接与后台任务"""

import pytest


@pytest.fixture(autouse=True)
async def _reset_db_pool_between_tests():
    """
    每个集成测试前后释放连接池，避免 asyncpg 连接被上一用例占用。

    配合 app.core.database 在 TESTING=1 时使用 NullPool。
    """
    from app.core.database import async_engine
    from app.services.user_seed import ensure_seed_users

    # ASGITransport 不执行 FastAPI lifespan；显式复现真实启动的用户种子事务，
    # 保证登录签发的 JWT subject 在后续数据库实时回查中存在。
    await ensure_seed_users()
    yield
    await async_engine.dispose()
