"""
健康检查路由模块

- /live: 存活检查（不查依赖）
- /ready: 就绪检查（DB + Redis）
- /: 详细健康（仅开发环境）
"""

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import config
from ..services.cache import cache

health_router = APIRouter()
_start_time = datetime.now()
_is_production = config['app']['env'] == 'production'


@health_router.get('/live')
async def health_live():
    """存活检查：进程存活，不查依赖"""
    return {'status': 'ok', 'uptime': int((datetime.now() - _start_time).total_seconds())}


@health_router.get('/ready')
async def health_ready():
    """就绪检查：DB + Redis 均可用时 200，否则 503"""
    from sqlalchemy import text

    from ..core.database import async_session_factory
    from ..core.redis_client import get_redis

    errors = []

    try:
        async with async_session_factory() as session:
            await session.execute(text('SELECT 1'))
    except Exception as e:
        errors.append(f'database: {e}')

    try:
        redis_client = get_redis()
        if not redis_client.ping():
            errors.append('redis: ping failed')
    except Exception as e:
        errors.append(f'redis: {e}')

    if errors:
        return JSONResponse(
            status_code=503,
            content={'status': 'not_ready', 'errors': errors},
        )

    return {'status': 'ready', 'uptime': int((datetime.now() - _start_time).total_seconds())}


@health_router.get('')
async def health_root():
    """详细健康检查（生产环境返回 404）"""
    if _is_production:
        return JSONResponse(status_code=404, content={'error': {'message': 'Not found'}})

    from ..core.database import check_tables_status

    try:
        db_status = await check_tables_status()
    except Exception as e:
        db_status = {'status': 'error', 'message': str(e)}

    return {
        'status': 'healthy',
        'uptime': int((datetime.now() - _start_time).total_seconds()),
        'cache': cache.get_stats(),
        'version': '1.0.0',
        'database': db_status,
    }
