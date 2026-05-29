"""
健康检查路由模块

提供服务健康状态检查接口：
- /live: 存活检查（用于 K8s livenessProbe）
- /: 详细健康状态（包含缓存统计、数据库状态、运行时长）

存活检查返回基本状态和运行时间；
详细检查额外返回缓存命中率、数据库表状态等运行时指标。
首次详细检查时会自动检测数据库表是否存在，缺失则自动建表。
"""

from datetime import datetime

from fastapi import APIRouter

from ..services.cache import cache

health_router = APIRouter()

# 服务启动时间，用于计算运行时长
_start_time = datetime.now()


@health_router.get('/live')
async def health_live():
    """
    存活检查

    用途：K8s livenessProbe 或负载均衡健康检测
    返回：基本状态 + 服务运行时长（秒）
    """
    return {'status': 'ok', 'uptime': int((datetime.now() - _start_time).total_seconds())}


@health_router.get('')
async def health_root():
    """
    详细健康检查

    返回：服务状态、运行时长、缓存统计、数据库状态、版本号
    首次调用时自动检测并初始化数据库表
    """
    from ..core.database import check_tables

    # 数据库检查（失败不阻塞基本健康检查）
    try:
        db_status = await check_tables()
    except Exception as e:
        db_status = {"status": "error", "message": str(e)}

    return {
        'status': 'healthy',
        'uptime': int((datetime.now() - _start_time).total_seconds()),
        'cache': cache.get_stats(),
        'version': '1.0.0',
        'database': db_status,
    }