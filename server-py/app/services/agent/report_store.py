"""
报告持久化模块（Redis 实现）

Agent 生成的报告按用户隔离存储：
- 元数据 Key：report:{user_id}:{id}
- 列表 Key：reports:list:{user_id}
- TTL：24 小时
"""

import asyncio
import hashlib
import json

from ...core.redis_client import get_redis
from ...utils.business_time import business_now, utc_now_naive

_REPORT_KEY_PREFIX = "report:"
_TTL_SECONDS = 24 * 3600  # 24 小时
_MAX_LIST_SIZE = 100  # 最多保留 100 条


class ReportStorageError(RuntimeError):
    """报告未能完整写入持久化存储。"""


def _list_key(user_id: str) -> str:
    return f"reports:list:{user_id}"


def _report_key(user_id: str, report_id: str) -> str:
    return f"{_REPORT_KEY_PREFIX}{user_id}:{report_id}"


def _generate_id(title, content):
    raw = f"{title}||{content[:200]}||{utc_now_naive().isoformat()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _save_report_sync(title: str, content: str, user_id: str) -> dict:
    r = get_redis()
    report_id = _generate_id(title, content)
    now = business_now().isoformat()

    meta = {
        "id": report_id,
        "title": title,
        "savedAt": now,
        "charCount": len(content),
        "userId": user_id,
    }

    try:
        # 单次 pipeline 提交，减少往返并保证一组写入一起下发。
        pipe = r.pipeline()
        pipe.setex(
            _report_key(user_id, report_id),
            _TTL_SECONDS,
            json.dumps({"meta": meta, "content": content}, ensure_ascii=False),
        )
        list_key = _list_key(user_id)
        pipe.lpush(list_key, report_id)
        pipe.ltrim(list_key, 0, _MAX_LIST_SIZE - 1)
        pipe.expire(list_key, _TTL_SECONDS)
        pipe.execute()
        return meta
    except Exception as err:
        raise ReportStorageError("报告持久化失败") from err


async def save_report(title: str, content: str, user_id: str) -> dict:
    """保存报告到 Redis（线程池执行同步 redis-py），返回 {id, title, savedAt}"""
    return await asyncio.to_thread(_save_report_sync, title, content, user_id)


def _get_report_sync(report_id: str, user_id: str):
    try:
        raw = get_redis().get(_report_key(user_id, report_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def get_report(report_id: str, user_id: str):
    """获取完整报告内容（仅本人）"""
    return await asyncio.to_thread(_get_report_sync, report_id, user_id)


def _list_reports_sync(user_id: str) -> list:
    try:
        r = get_redis()
        ids = r.lrange(_list_key(user_id), 0, -1)
        if not ids:
            return []
        # 用 MGET 一次取回，避免最多 100 次串行 GET。
        keys = [_report_key(user_id, rid) for rid in ids]
        raws = r.mget(keys)
        reports = []
        for raw in raws:
            if raw:
                entry = json.loads(raw)
                reports.append(entry["meta"])
        return reports
    except Exception:
        return []


async def list_reports(user_id: str) -> list:
    """列出当前用户最近的报告（仅元数据）"""
    return await asyncio.to_thread(_list_reports_sync, user_id)


def _delete_report_sync(report_id: str, user_id: str) -> bool:
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.delete(_report_key(user_id, report_id))
        pipe.lrem(_list_key(user_id), 0, report_id)
        pipe.execute()
        return True
    except Exception:
        return False


async def delete_report(report_id: str, user_id: str) -> bool:
    """删除报告（仅本人）"""
    return await asyncio.to_thread(_delete_report_sync, report_id, user_id)
