"""
Redis 客户端封装

提供全局单例 Redis 连接，基于连接池复用。
配置通过 config['redis'] 读取。
"""

import redis

from ..config import config


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        rc = config['redis']
        _pool = redis.ConnectionPool(
            host=rc['host'],
            port=rc['port'],
            password=rc['password'],
            db=rc['db'],
            decode_responses=True,
            max_connections=10,
        )
    return _pool


def get_redis():
    """获取 Redis 客户端单例"""
    return redis.Redis(connection_pool=_get_pool())


def close_redis():
    """关闭连接池（应用退出时调用）"""
    global _pool
    if _pool:
        _pool.disconnect()
        _pool = None
