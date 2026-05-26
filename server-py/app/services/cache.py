# 精确缓存：相同的 system + message 直接返回缓存，不调 API
import hashlib
import time

from ..config import config


class ExactCache:
    def __init__(self):
        self.store = {}  # key -> { content, ts, tokens }
        self.stats = {'hits': 0, 'misses': 0, 'saved_tokens': 0}

    def _key(self, system_prompt, message):
        raw = f'{system_prompt or ""}||{message}'
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, system_prompt, message):
        k = self._key(system_prompt, message)
        entry = self.store.get(k)

        if not entry:
            self.stats['misses'] += 1
            return None

        # TTL 过期检查（config 里是毫秒，Python 用秒）
        if time.time() - entry['ts'] > config['cache']['ttl'] / 1000:
            del self.store[k]
            self.stats['misses'] += 1
            return None

        self.stats['hits'] += 1
        self.stats['saved_tokens'] += entry.get('tokens', 0)
        return entry

    def set(self, system_prompt, message, data):
        k = self._key(system_prompt, message)
        self.store[k] = {
            'content': data['content'],
            'tokens': data.get('tokens', 0),
            'ts': time.time(),
        }

        # LRU：超 500 条清最老 50 条
        if len(self.store) > 500:
            sorted_keys = sorted(self.store.items(), key=lambda x: x[1]['ts'])
            for old_k, _ in sorted_keys[:50]:
                del self.store[old_k]

    @property
    def hit_rate(self):
        total = self.stats['hits'] + self.stats['misses']
        return f"{self.stats['hits'] / total * 100:.1f}%" if total else '0%'

    def get_stats(self):
        return {
            'size': len(self.store),
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'hitRate': self.hit_rate,
            'savedTokens': self.stats['saved_tokens'],
        }


# 全局单例
cache = ExactCache()
