"""
Redis 客户端封装（同步 redis-py + 全局连接池单例）

约定：
- decode_responses=True，所有读写都是 str，业务层不处理 bytes
- redis-py 为同步阻塞客户端，async 路径调用必须包 asyncio.to_thread
  （见 token_store / report_store / cache 等调用方），禁止在事件循环内直连
- socket 超时 2s：Redis 故障时快速失败，让各业务按自身策略降级或 fail-closed
"""

import redis

from ..config import config


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        rc = config["redis"]
        _pool = redis.ConnectionPool(
            host=rc["host"],
            port=rc["port"],
            password=rc["password"],
            db=rc["db"],
            decode_responses=True,
            max_connections=10,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
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
