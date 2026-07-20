"""
用量监控服务：LLM 调用记录、持久化管线与统计聚合

职责（原挂在 routes/monitor.py，下沉后消除 service→routes 反向依赖）：
- record_api_call：interceptor/chat 每次 LLM 调用（含缓存命中）同步登记
- 持久化：记录进内存 _calls（最近 500 条，降级展示用）与 _pending 队列，
  后台 _flush_loop 每 30s 批量写 PostgreSQL；DB 故障时队列封顶丢弃最旧记录
- 统计：/stats 的完整载荷构造（PostgreSQL 有界聚合，失败降级本 worker 内存）
- 日预算：内存镜像 + system_settings 持久化（强制扣费由 budget_guard 独立执行）

routes/monitor.py 只保留 HTTP 端点并调用本模块。
"""

import asyncio
import math
import threading
from datetime import date, timedelta

from sqlalchemy import Date as SQLDate
from sqlalchemy import and_, case, cast, func, select

from ..utils.business_time import (
    business_date,
    business_day_utc_bounds,
    business_timezone_name,
    parse_utc_naive,
    to_business_datetime,
    utc_now_naive,
)
from ..utils.logger import logger
from .cache import cache
from .pricing import (
    blended_price_cny_per_million,
    calculate_token_cost,
    get_pricing,
)

# ── 内存缓存（数据库异常时降级及最近记录）──────────────────────
_start_time = utc_now_naive()
_calls: list[dict] = []

# ── DB 持久化队列 ─────────────────────────────────────────────
_pending: list[dict] = []
_flush_lock = asyncio.Lock()
_pending_lock = threading.Lock()
_flush_task: asyncio.Task | None = None
# DB 长时间不可用时限制待写队列上限，避免内存无界增长 OOM；超限丢弃最旧记录。
_MAX_PENDING = 10_000
_pending_dropped = 0


# ── 日预算（持久化到 system_settings）──────────────────────────
_daily_budget: float = 50.0


async def load_budget_from_db():
    """启动时从 DB 加载预算"""
    global _daily_budget
    from .budget_guard import load_budget

    _daily_budget = await load_budget()


async def update_daily_budget(value: float) -> None:
    """更新日预算：先持久化到 system_settings，成功后刷新内存镜像"""
    global _daily_budget
    from .budget_guard import save_budget

    await save_budget(value)
    _daily_budget = value


def record_api_call(
    feature="chat",
    input_tokens=0,
    output_tokens=0,
    latency_ms=0,
    from_cache=False,
    error=False,
    model_name=None,
    started_at=None,
):
    """
    记录一次 API 调用（同步，兼容 interceptor 的 sync/async 调用）

    费用统一由 services.pricing 按当前环境配置计算。
    """
    cost = calculate_token_cost(
        input_tokens,
        output_tokens,
        model_name=model_name,
    )
    event_time = parse_utc_naive(started_at or utc_now_naive())
    record = {
        # DB DateTime 全部使用 UTC-naive；业务时区仅用于查询边界与 API 展示。
        "time": event_time.isoformat(),
        "feature": feature,
        "inputT": input_tokens,
        "outputT": output_tokens,
        "costUSD": cost.usd,
        "costCNY": cost.cny,
        "latencyMs": round(latency_ms, 1),
        "fromCache": from_cache,
        "error": error,
    }
    global _pending_dropped
    with _pending_lock:
        _calls.append(record)
        _pending.append(record)
        # 内存只保留最近 500 条
        if len(_calls) > 500:
            _calls.pop(0)
        # 待写队列封顶：DB 长时间故障时丢弃最旧记录并计数，防止 OOM
        if len(_pending) > _MAX_PENDING:
            overflow = len(_pending) - _MAX_PENDING
            del _pending[:overflow]
            _pending_dropped += overflow


def memory_day_cost(selected_day: date) -> float:
    """本 worker 内存记录的当日实付费用（budget_guard 数据库不可用时的降级依据）"""
    return sum(
        float(call["costCNY"])
        for call in _calls
        if business_date(call["time"]) == selected_day and not call["fromCache"]
    )


# ── DB 持久化逻辑 ─────────────────────────────────────────────


async def _load_from_db():
    """启动时从 DB 恢复最近记录到内存"""
    try:
        from ..core.database import async_session_factory
        from ..models.entities import MonitorRecord
        from sqlalchemy import select, desc

        async with async_session_factory() as session:
            result = await session.execute(select(MonitorRecord).order_by(desc(MonitorRecord.time)).limit(500))
            rows = result.scalars().all()
            for r in reversed(rows):
                _calls.append(
                    {
                        "time": parse_utc_naive(r.time).isoformat(),
                        "feature": r.feature,
                        "inputT": r.input_tokens,
                        "outputT": r.output_tokens,
                        "costUSD": r.cost_usd,
                        "costCNY": r.cost_cny,
                        "latencyMs": r.latency_ms,
                        "fromCache": r.from_cache,
                        "error": r.error,
                    }
                )
        logger.info(f"[monitor] 从 DB 恢复了 {len(_calls)} 条记录")
    except Exception as e:
        logger.warn(f"[monitor] 从 DB 加载记录失败（首次启动表可能不存在）: {e}")


async def _flush_to_db():
    """批量将 _pending 队列写入 DB"""
    async with _flush_lock:
        with _pending_lock:
            to_insert = _pending[:]
            _pending.clear()
    if not to_insert:
        return

    try:
        from ..core.database import get_db_context
        from ..models.entities import MonitorRecord

        async with get_db_context() as session:
            for r in to_insert:
                session.add(
                    MonitorRecord(
                        time=parse_utc_naive(r["time"]),
                        feature=r["feature"],
                        input_tokens=r["inputT"],
                        output_tokens=r["outputT"],
                        cost_usd=r["costUSD"],
                        cost_cny=r["costCNY"],
                        latency_ms=r["latencyMs"],
                        from_cache=r["fromCache"],
                        error=r.get("error", False),
                    )
                )
        logger.info(f"[monitor] 持久化了 {len(to_insert)} 条记录到 DB")
    except Exception as e:
        logger.warn(f"[monitor] 持久化失败，记录放回队列: {e}")
        # 失败时放回队列，下次重试；仍受 _MAX_PENDING 封顶，避免无界增长
        global _pending_dropped
        async with _flush_lock:
            with _pending_lock:
                combined = to_insert + _pending
                if len(combined) > _MAX_PENDING:
                    overflow = len(combined) - _MAX_PENDING
                    combined = combined[overflow:]
                    _pending_dropped += overflow
                _pending[:] = combined


async def _flush_loop():
    """后台循环：每 30s 批量刷写一次"""
    while True:
        await asyncio.sleep(30)
        try:
            await _flush_to_db()
        except Exception as e:
            logger.warn(f"[monitor] flush 循环异常: {e}")


async def start_flush_task():
    """启动持久化后台任务（由 main.py lifespan 调用）"""
    global _flush_task
    if _flush_task is not None and not _flush_task.done():
        return
    await _load_from_db()
    _flush_task = asyncio.create_task(_flush_loop())
    logger.info("[monitor] 后台持久化任务已启动")


async def stop_flush_task():
    """停止持久化后台任务"""
    global _flush_task
    if _flush_task:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
        _flush_task = None
    # 关闭前最后 flush 一次
    await _flush_to_db()
    logger.info("[monitor] 后台持久化任务已停止")


# ── 统计辅助函数 ───────────────────────────────────────────────


def _percentile(arr, p):
    """计算百分位数"""
    if not arr:
        return 0
    s = sorted(arr)
    idx = max(0, math.ceil(len(s) * p / 100) - 1)
    return s[idx]


def _get_last7_days(calls, selected_day: date | None = None):
    """计算最近 7 天的统计（用于折线图）"""
    last_day = selected_day or business_date()
    days = []
    for i in range(6, -1, -1):
        d = last_day - timedelta(days=i)
        day_str = d.isoformat()
        day_calls = [c for c in calls if business_date(c["time"]) == d]
        days.append(
            {
                "date": day_str,
                "label": f"{d.month}/{d.day}",
                "totalCalls": len(day_calls),
                "apiCalls": len([c for c in day_calls if not c["fromCache"]]),
                "inputT": sum(c["inputT"] for c in day_calls),
                "outputT": sum(c["outputT"] for c in day_calls),
                "costCNY": round(sum(c["costCNY"] for c in day_calls if not c["fromCache"]), 4),
            }
        )
    return days


_FEATURE_NAMES = {
    "chat": "对话助手",
    "knowledge": "RAG 知识库",
    "agent": "任务 Agent",
    "workflow": "内容工作流",
    "erp": "ERP 审批",
    "prompt": "Prompt 调试",
}


def _get_by_feature(calls):
    """按功能模块统计调用量、费用、Token"""
    features = {}
    for c in calls:
        f = c["feature"]
        if f not in features:
            features[f] = {"calls": 0, "costCNY": 0, "tokens": 0}
        features[f]["calls"] += 1
        if not c["fromCache"]:
            features[f]["costCNY"] += c["costCNY"]
        features[f]["tokens"] += c["inputT"] + c["outputT"]

    return sorted(
        [
            {
                "feature": k,
                "label": _FEATURE_NAMES.get(k, k),
                "calls": v["calls"],
                "costCNY": round(v["costCNY"], 4),
                "tokens": v["tokens"],
            }
            for k, v in features.items()
        ],
        key=lambda x: x["calls"],
        reverse=True,
    )


async def _query_stats_from_db(selected_day: date) -> dict:
    """用 PostgreSQL 聚合指定日及最近 7 日数据，所有查询都有时间边界。"""
    from ..core.database import async_session_factory
    from ..models.entities import MonitorRecord

    today_start, tomorrow_start = business_day_utc_bounds(selected_day)
    week_start, _ = business_day_utc_bounds(selected_day - timedelta(days=6))

    api_call_condition = MonitorRecord.from_cache.is_(False)
    latency_value = case(
        (
            and_(api_call_condition, MonitorRecord.latency_ms > 0),
            MonitorRecord.latency_ms,
        ),
        else_=None,
    )
    today_stmt = select(
        func.count(MonitorRecord.id).label("total_calls"),
        func.coalesce(
            func.sum(case((api_call_condition, 1), else_=0)),
            0,
        ).label("api_calls"),
        func.coalesce(
            func.sum(case((MonitorRecord.from_cache.is_(True), 1), else_=0)),
            0,
        ).label("cache_hits"),
        func.coalesce(func.sum(MonitorRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(MonitorRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(
            func.sum(case((api_call_condition, MonitorRecord.cost_cny), else_=0.0)),
            0.0,
        ).label("cost_cny"),
        func.coalesce(func.percentile_cont(0.5).within_group(latency_value), 0.0).label("p50"),
        func.coalesce(func.percentile_cont(0.9).within_group(latency_value), 0.0).label("p90"),
        func.coalesce(func.percentile_cont(0.99).within_group(latency_value), 0.0).label("p99"),
        func.coalesce(func.avg(latency_value), 0.0).label("avg_latency"),
    ).where(
        MonitorRecord.time >= today_start,
        MonitorRecord.time < tomorrow_start,
    )

    business_day = cast(
        func.timezone(business_timezone_name(), func.timezone("UTC", MonitorRecord.time)),
        SQLDate,
    ).label("day")
    last7_stmt = (
        select(
            business_day,
            func.count(MonitorRecord.id).label("total_calls"),
            func.coalesce(
                func.sum(case((api_call_condition, 1), else_=0)),
                0,
            ).label("api_calls"),
            func.coalesce(func.sum(MonitorRecord.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(MonitorRecord.output_tokens), 0).label("output_tokens"),
            func.coalesce(
                func.sum(case((api_call_condition, MonitorRecord.cost_cny), else_=0.0)),
                0.0,
            ).label("cost_cny"),
        )
        .where(
            MonitorRecord.time >= week_start,
            MonitorRecord.time < tomorrow_start,
        )
        .group_by(business_day)
        .order_by(business_day)
    )

    feature_stmt = (
        select(
            MonitorRecord.feature,
            func.count(MonitorRecord.id).label("calls"),
            func.coalesce(
                func.sum(case((api_call_condition, MonitorRecord.cost_cny), else_=0.0)),
                0.0,
            ).label("cost_cny"),
            func.coalesce(
                func.sum(MonitorRecord.input_tokens + MonitorRecord.output_tokens),
                0,
            ).label("tokens"),
        )
        .where(
            MonitorRecord.time >= today_start,
            MonitorRecord.time < tomorrow_start,
        )
        .group_by(MonitorRecord.feature)
        .order_by(func.count(MonitorRecord.id).desc())
    )

    recent_stmt = (
        select(
            MonitorRecord.time,
            MonitorRecord.feature,
            MonitorRecord.input_tokens,
            MonitorRecord.output_tokens,
            MonitorRecord.cost_cny,
            MonitorRecord.latency_ms,
            MonitorRecord.from_cache,
            MonitorRecord.error,
        )
        .order_by(MonitorRecord.time.desc())
        .limit(50)
    )

    async with async_session_factory() as session:
        today_result = await session.execute(today_stmt)
        last7_result = await session.execute(last7_stmt)
        feature_result = await session.execute(feature_stmt)
        recent_result = await session.execute(recent_stmt)

    return {
        "today": today_result.mappings().one(),
        "last7": last7_result.mappings().all(),
        "features": feature_result.mappings().all(),
        "recent": recent_result.mappings().all(),
    }


def _format_last7_rows(rows, selected_day: date) -> list[dict]:
    """把近 7 日聚合行补齐为连续 7 天序列（无数据的日期填 0，保证图表 X 轴完整）。"""
    rows_by_day = {}
    for row in rows:
        raw_day = row["day"]
        day_text = raw_day.isoformat() if hasattr(raw_day, "isoformat") else str(raw_day)
        rows_by_day[day_text] = row

    days = []
    for offset in range(6, -1, -1):
        current_day = selected_day - timedelta(days=offset)
        row = rows_by_day.get(current_day.isoformat())
        days.append(
            {
                "date": current_day.isoformat(),
                "label": f"{current_day.month}/{current_day.day}",
                "totalCalls": int(row["total_calls"]) if row else 0,
                "apiCalls": int(row["api_calls"]) if row else 0,
                "inputT": int(row["input_tokens"]) if row else 0,
                "outputT": int(row["output_tokens"]) if row else 0,
                "costCNY": round(float(row["cost_cny"]), 4) if row else 0,
            }
        )
    return days


def _format_feature_rows(rows) -> list[dict]:
    """按业务域聚合行 → 前端图表契约（feature 补中文 label）。"""
    return [
        {
            "feature": row["feature"],
            "label": _FEATURE_NAMES.get(row["feature"], row["feature"]),
            "calls": int(row["calls"] or 0),
            "costCNY": round(float(row["cost_cny"] or 0), 4),
            "tokens": int(row["tokens"] or 0),
        }
        for row in rows
    ]


def _format_recent_rows(rows) -> list[dict]:
    """最近调用明细行 → 前端表格契约（时间转业务时区展示）。"""
    recent_calls = []
    for row in rows:
        raw_time = row["time"]
        time_text = to_business_datetime(raw_time).isoformat()
        recent_calls.append(
            {
                "time": time_text,
                "feature": row["feature"],
                "inputT": int(row["input_tokens"] or 0),
                "outputT": int(row["output_tokens"] or 0),
                "costCNY": round(float(row["cost_cny"] or 0), 5),
                "latencyMs": round(float(row["latency_ms"] or 0), 1),
                "fromCache": bool(row["from_cache"]),
                "error": bool(row["error"]),
            }
        )
    return recent_calls


# ── /stats 载荷构造 ────────────────────────────────────────────


async def build_stats_payload() -> dict:
    """构造 /monitor/stats 完整响应：优先数据库有界聚合，失败降级本 worker 内存。"""
    global _daily_budget
    selected_day = business_date()

    # 先尽力持久化本 worker 的待写记录，再从数据库做有界聚合。
    await _flush_to_db()
    try:
        database_stats = await _query_stats_from_db(selected_day)
        stats_source = "database"
        today = database_stats["today"]
        total_calls = int(today["total_calls"])
        api_calls = int(today["api_calls"])
        cache_hits = int(today["cache_hits"])
        token_input_today = int(today["input_tokens"])
        token_output_today = int(today["output_tokens"])
        total_cost = float(today["cost_cny"])
        latency = {
            "p50": float(today["p50"]),
            "p90": float(today["p90"]),
            "p99": float(today["p99"]),
            "avg": round(float(today["avg_latency"])),
        }
        by_feature = _format_feature_rows(database_stats["features"])
        last7_days = _format_last7_rows(database_stats["last7"], selected_day)
        recent_calls = _format_recent_rows(database_stats["recent"])
    except Exception as exc:
        # 管理面板保留可用性，但明确记录数据库降级；预算强制仍由 Redis 守卫独立执行。
        logger.error(f"[monitor] SQL 聚合失败，/stats 降级使用本 worker 内存记录: {exc}")
        stats_source = "memory_fallback"
        today_calls = [call for call in _calls if business_date(call["time"]) == selected_day]
        latencies = [call["latencyMs"] for call in today_calls if not call["fromCache"] and call["latencyMs"] > 0]
        total_calls = len(today_calls)
        cache_hits = len([call for call in today_calls if call["fromCache"]])
        api_calls = total_calls - cache_hits
        token_input_today = sum(call["inputT"] for call in today_calls)
        token_output_today = sum(call["outputT"] for call in today_calls)
        total_cost = sum(call["costCNY"] for call in today_calls if not call["fromCache"])
        latency = {
            "p50": _percentile(latencies, 50),
            "p90": _percentile(latencies, 90),
            "p99": _percentile(latencies, 99),
            "avg": round(sum(latencies) / len(latencies)) if latencies else 0,
        }
        by_feature = _get_by_feature(today_calls)
        last7_days = _get_last7_days(_calls, selected_day)
        recent_calls = _format_recent_rows(
            [
                {
                    "time": call["time"],
                    "feature": call["feature"],
                    "input_tokens": call["inputT"],
                    "output_tokens": call["outputT"],
                    "cost_cny": call["costCNY"],
                    "latency_ms": call["latencyMs"],
                    "from_cache": call["fromCache"],
                    "error": call.get("error", False),
                }
                for call in reversed(_calls[-50:])
            ]
        )

    from .budget_guard import load_budget

    _daily_budget = await load_budget()
    pricing = get_pricing()
    average_price_cny = blended_price_cny_per_million(pricing)
    uptime = (utc_now_naive() - _start_time).total_seconds()
    token_budget = round(_daily_budget / average_price_cny * 1_000_000)
    token_used = token_input_today + token_output_today

    return {
        "overview": {
            "totalCallsToday": total_calls,
            "apiCallsToday": api_calls,
            "cacheHitsToday": cache_hits,
            "cacheHitRate": f"{cache_hits / total_calls * 100:.1f}%" if total_calls else "0%",
            "tokenInputToday": token_input_today,
            "tokenOutputToday": token_output_today,
            "costCNYToday": round(total_cost, 4),
            "dailyBudget": _daily_budget,
            "budgetUsedPct": (
                min(100, math.ceil(total_cost / _daily_budget * 10000) / 100) if _daily_budget > 0 else 0
            ),
            "tokenBudget": token_budget,
            "tokenUsedPct": min(100, math.ceil(token_used / token_budget * 10000) / 100) if token_budget else 0,
            "uptimeSeconds": int(uptime),
            "statsSource": stats_source,
            "businessDate": selected_day.isoformat(),
            "businessTimezone": business_timezone_name(),
            "model": pricing.model_name,
            "pricing": {
                "input": pricing.input_usd_per_million,
                "output": pricing.output_usd_per_million,
                "unit": "USD/M",
                "exchangeRate": pricing.usd_cny_exchange_rate,
                "pricingModel": pricing.model_name,
                "source": pricing.source,
            },
        },
        "latency": latency,
        "byFeature": by_feature,
        "last7Days": last7_days,
        "recentCalls": recent_calls,
        "cacheStats": await asyncio.to_thread(cache.get_stats),
        # DB 故障期间因队列封顶被丢弃的监控记录数；非 0 说明统计存在缺口
        "pendingDropped": _pending_dropped,
    }
