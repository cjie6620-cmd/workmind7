"""
报告持久化模块（Redis 实现）

Agent 生成的报告按用户隔离存储：
- 元数据 Key：report:{user_id}:{id}
- 列表 Key：reports:list:{user_id}
- TTL：24 小时
"""

import hashlib
import json
from datetime import datetime, timezone, timedelta

from ...core.redis_client import get_redis

_REPORT_KEY_PREFIX = 'report:'
_TTL_SECONDS = 24 * 3600  # 24 小时
_MAX_LIST_SIZE = 100       # 最多保留 100 条


def _list_key(user_id: str) -> str:
    return f'reports:list:{user_id}'


def _report_key(user_id: str, report_id: str) -> str:
    return f'{_REPORT_KEY_PREFIX}{user_id}:{report_id}'


def _generate_id(title, content):
    raw = f'{title}||{content[:200]}||{datetime.now().isoformat()}'
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def save_report(title: str, content: str, user_id: str) -> dict:
    """保存报告到 Redis，返回 {id, title, savedAt}"""
    r = get_redis()
    report_id = _generate_id(title, content)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()

    meta = {
        'id': report_id,
        'title': title,
        'savedAt': now,
        'charCount': len(content),
        'userId': user_id,
    }

    try:
        r.setex(
            _report_key(user_id, report_id),
            _TTL_SECONDS,
            json.dumps({'meta': meta, 'content': content}, ensure_ascii=False),
        )
        list_key = _list_key(user_id)
        r.lpush(list_key, report_id)
        r.ltrim(list_key, 0, _MAX_LIST_SIZE - 1)
        r.expire(list_key, _TTL_SECONDS)
        return meta
    except Exception:
        return meta


def get_report(report_id: str, user_id: str):
    """获取完整报告内容（仅本人）"""
    try:
        raw = get_redis().get(_report_key(user_id, report_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def list_reports(user_id: str) -> list:
    """列出当前用户最近的报告（仅元数据）"""
    try:
        r = get_redis()
        ids = r.lrange(_list_key(user_id), 0, -1)
        reports = []
        for rid in ids:
            raw = r.get(_report_key(user_id, rid))
            if raw:
                entry = json.loads(raw)
                reports.append(entry['meta'])
        return reports
    except Exception:
        return []


def delete_report(report_id: str, user_id: str) -> bool:
    """删除报告（仅本人）"""
    try:
        r = get_redis()
        r.delete(_report_key(user_id, report_id))
        r.lrem(_list_key(user_id), 0, report_id)
        return True
    except Exception:
        return False
