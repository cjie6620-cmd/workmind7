"""
精确缓存模块

实现精确匹配缓存：
- 相同的 system prompt + message → 返回缓存结果
- 支持 TTL 过期
- 支持 LRU 淘汰

缓存策略：
- Key：MD5(system_prompt + message)
- TTL：默认 30 分钟（可配置）
- 上限：500 条，超出后清除最老的 50 条
"""

import hashlib
import time

from ..config import config


class ExactCache:
    """
    精确缓存实现

    用于避免重复调用 LLM API，节省成本和提升响应速度。
    适用于客服问答等场景，相同问题返回相同答案。
    """

    def __init__(self):
        self.store = {}  # key -> { content, ts, tokens }
        self.stats = {'hits': 0, 'misses': 0, 'saved_tokens': 0}

    def _key(self, system_prompt, message):
        """生成缓存 key"""
        raw = f'{system_prompt or ""}||{message}'
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, system_prompt, message):
        """
        获取缓存

        返回：缓存内容或 None（未命中或已过期）
        """
        k = self._key(system_prompt, message)
        entry = self.store.get(k)

        if not entry:
            self.stats['misses'] += 1
            return None

        # TTL 过期检查（config 里是毫秒，转为秒）
        if time.time() - entry['ts'] > config['cache']['ttl'] / 1000:
            del self.store[k]
            self.stats['misses'] += 1
            return None

        self.stats['hits'] += 1
        self.stats['saved_tokens'] += entry.get('tokens', 0)
        return entry

    def set(self, system_prompt, message, data):
        """设置缓存"""
        k = self._key(system_prompt, message)
        self.store[k] = {
            'content': data['content'],
            'tokens': data.get('tokens', 0),
            'ts': time.time(),
        }

        # LRU 淘汰：超过 500 条时清除最老的 50 条
        if len(self.store) > 500:
            sorted_keys = sorted(self.store.items(), key=lambda x: x[1]['ts'])
            for old_k, _ in sorted_keys[:50]:
                del self.store[old_k]

    @property
    def hit_rate(self):
        """计算缓存命中率"""
        total = self.stats['hits'] + self.stats['misses']
        return f"{self.stats['hits'] / total * 100:.1f}%" if total else '0%'

    def get_stats(self):
        """获取缓存统计"""
        return {
            'size': len(self.store),
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'hitRate': self.hit_rate,
            'savedTokens': self.stats['saved_tokens'],
        }


# 全局单例
cache = ExactCache()