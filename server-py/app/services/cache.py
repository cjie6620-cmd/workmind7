"""
精确缓存模块（Redis 实现）

利用 Redis 存储 + 原生 LRU 淘汰策略：
- Key 前缀 cache:，避免与其他业务冲突
- TTL 由 Redis setex 原生管理
- 淘汰策略依赖 Redis 配置 maxmemory-policy allkeys-lru
- 统计信息（hits/misses/saved_tokens）用 Redis Hash 存储
"""

import hashlib
import json

from ..config import config
from ..core.redis_client import get_redis


# 缓存 key 前缀
_PREFIX = 'cache:'
# 统计 key
_STATS_KEY = 'cache:stats'


class ExactCache:
    """
    精确缓存实现（Redis 版）

    用于避免重复调用 LLM API，节省成本和提升响应速度。
    """

    def _key(self, system_prompt, message):
        """生成缓存 key"""
        raw = f'{system_prompt or ""}||{message}'
        return f'{_PREFIX}{hashlib.md5(raw.encode()).hexdigest()}'

    def _ttl_seconds(self):
        """TTL 毫秒转秒"""
        return config['cache']['ttl'] // 1000

    def _incr_stat(self, field, amount=1):
        """原子递增统计字段"""
        try:
            get_redis().hincrby(_STATS_KEY, field, amount)
        except Exception:
            pass

    def get(self, system_prompt, message):
        """
        获取缓存

        返回：缓存内容或 None（未命中或已过期）
        """
        k = self._key(system_prompt, message)
        try:
            raw = get_redis().get(k)
        except Exception:
            raw = None

        if not raw:
            self._incr_stat('misses')
            return None

        self._incr_stat('hits')
        entry = json.loads(raw)
        self._incr_stat('saved_tokens', entry.get('tokens', 0))
        return entry

    def set(self, system_prompt, message, data):
        """设置缓存，TTL 由 Redis setex 原生管理"""
        k = self._key(system_prompt, message)
        entry = {
            'content': data['content'],
            'tokens': data.get('tokens', 0),
        }
        try:
            get_redis().setex(k, self._ttl_seconds(), json.dumps(entry, ensure_ascii=False))
        except Exception:
            pass

    @property
    def hit_rate(self):
        """计算缓存命中率"""
        try:
            stats = get_redis().hgetall(_STATS_KEY)
        except Exception:
            return '0%'
        hits = int(stats.get('hits', 0))
        misses = int(stats.get('misses', 0))
        total = hits + misses
        return f'{hits / total * 100:.1f}%' if total else '0%'

    def get_stats(self):
        """获取缓存统计"""
        try:
            r = get_redis()
            stats = r.hgetall(_STATS_KEY)
            size = sum(1 for _ in r.scan_iter(match=f'{_PREFIX}*'))
        except Exception:
            stats = {}
            size = 0

        return {
            'size': size,
            'hits': int(stats.get('hits', 0)),
            'misses': int(stats.get('misses', 0)),
            'hitRate': self.hit_rate,
            'savedTokens': int(stats.get('saved_tokens', 0)),
        }


# 全局单例
cache = ExactCache()
