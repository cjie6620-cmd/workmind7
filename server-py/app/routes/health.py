# 健康检查路由
from datetime import datetime

from fastapi import APIRouter

from ..services.cache import cache

health_router = APIRouter()

_start_time = datetime.now()


@health_router.get('/live')
async def health_live():
    return {'status': 'ok', 'uptime': int((datetime.now() - _start_time).total_seconds())}


@health_router.get('')
async def health_root():
    return {
        'status': 'healthy',
        'uptime': int((datetime.now() - _start_time).total_seconds()),
        'cache': cache.get_stats(),
        'version': '1.0.0',
    }
