"""
报告持久化模块（Redis 实现）

Agent 生成的报告临时存储在 Redis：
- 元数据 Key：report:{id}
- 列表 Key：reports:list（后进先出）
- TTL：24 小时
"""

import hashlib
import json
from datetime import datetime, timezone, timedelta

from ...core.redis_client import get_redis

_REPORT_KEY_PREFIX = 'report:'
_REPORT_LIST_KEY = 'reports:list'
_TTL_SECONDS = 24 * 3600  # 24 小时
_MAX_LIST_SIZE = 100       # 最多保留 100 条


def _generate_id(title, content):
    raw = f'{title}||{content[:200]}||{datetime.now().isoformat()}'
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def save_report(title, content):
    """保存报告到 Redis，返回 {id, title, savedAt}"""
    r = get_redis()
    report_id = _generate_id(title, content)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()

    meta = {
        'id': report_id,
        'title': title,
        'savedAt': now,
        'charCount': len(content),
    }

    try:
        # 存储完整内容
        r.setex(f'{_REPORT_KEY_PREFIX}{report_id}', _TTL_SECONDS,
                json.dumps({'meta': meta, 'content': content}, ensure_ascii=False))
        # 索引列表（头部插入）
        r.lpush(_REPORT_LIST_KEY, report_id)
        r.ltrim(_REPORT_LIST_KEY, 0, _MAX_LIST_SIZE - 1)
        # 列表也设置 TTL
        r.expire(_REPORT_LIST_KEY, _TTL_SECONDS)
        return meta
    except Exception:
        # Redis 不可用时仍然返回元数据（报告已通过工具返回给前端）
        return meta


def get_report(report_id):
    """获取完整报告内容"""
    try:
        raw = get_redis().get(f'{_REPORT_KEY_PREFIX}{report_id}')
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def list_reports():
    """列出最近的报告（仅元数据）"""
    try:
        r = get_redis()
        ids = r.lrange(_REPORT_LIST_KEY, 0, -1)
        reports = []
        for rid in ids:
            raw = r.get(f'{_REPORT_KEY_PREFIX}{rid}')
            if raw:
                entry = json.loads(raw)
                reports.append(entry['meta'])
        return reports
    except Exception:
        return []


def delete_report(report_id):
    """删除报告"""
    try:
        r = get_redis()
        r.delete(f'{_REPORT_KEY_PREFIX}{report_id}')
        r.lrem(_REPORT_LIST_KEY, 0, report_id)
        return True
    except Exception:
        return False
