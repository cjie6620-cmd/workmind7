"""
用量监控路由模块

提供 API 调用统计和成本分析：
- GET /stats: 获取详细统计信息
- PUT /budget: 设置日预算上限

持久化策略：
- 内存 _calls 列表保持实时读取性能
- 每次 record 同时追加到 _pending 队列
- 后台 _flush_loop 每 30s 批量写入 PostgreSQL
- 启动时从 DB 恢复最近 500 条记录
"""

import asyncio
import math
from datetime import datetime, date

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..services.cache import cache
from ..schemas.requests import BudgetUpdateRequest
from ..utils.logger import logger

monitor_router = APIRouter()

# ── 内存缓存（保证 /stats 接口实时性）──────────────────────────
_start_time = datetime.now()
_calls: list[dict] = []

# ── DB 持久化队列 ─────────────────────────────────────────────
_pending: list[dict] = []
_flush_lock = asyncio.Lock()
_flush_task: asyncio.Task | None = None


# ── 日预算（持久化到 system_settings）──────────────────────────
_daily_budget = 50


async def load_budget_from_db():
    """启动时从 DB 加载预算"""
    global _daily_budget
    from ..services.budget_guard import load_budget
    _daily_budget = await load_budget()


def get_daily_budget() -> float:
    return _daily_budget


def record_api_call(feature='chat', input_tokens=0, output_tokens=0,
                    latency_ms=0, from_cache=False, error=False):
    """
    记录一次 API 调用（同步，兼容 interceptor 的 sync/async 调用）

    自动计算费用（DeepSeek V4-Flash 定价）：
    - 输入：$0.14/M tokens
    - 输出：$0.28/M tokens
    - 汇率：7.2
    """
    cost_usd = (input_tokens / 1e6 * 0.14) + (output_tokens / 1e6 * 0.28)
    record = {
        'time': datetime.now().isoformat(),
        'feature': feature,
        'inputT': input_tokens,
        'outputT': output_tokens,
        'costUSD': cost_usd,
        'costCNY': cost_usd * 7.2,
        'latencyMs': round(latency_ms, 1),
        'fromCache': from_cache,
        'error': error,
    }
    _calls.append(record)
    _pending.append(record)
    # 内存只保留最近 500 条
    if len(_calls) > 500:
        _calls.pop(0)


# ── DB 持久化逻辑 ─────────────────────────────────────────────

async def _load_from_db():
    """启动时从 DB 恢复最近记录到内存"""
    try:
        from ..core.database import async_session_factory
        from ..models.entities import MonitorRecord
        from sqlalchemy import select, desc

        async with async_session_factory() as session:
            result = await session.execute(
                select(MonitorRecord).order_by(desc(MonitorRecord.time)).limit(500)
            )
            rows = result.scalars().all()
            for r in reversed(rows):
                _calls.append({
                    'time': r.time.isoformat(),
                    'feature': r.feature,
                    'inputT': r.input_tokens,
                    'outputT': r.output_tokens,
                    'costUSD': r.cost_usd,
                    'costCNY': r.cost_cny,
                    'latencyMs': r.latency_ms,
                    'fromCache': r.from_cache,
                    'error': r.error,
                })
        logger.info(f'[monitor] 从 DB 恢复了 {len(_calls)} 条记录')
    except Exception as e:
        logger.warning(f'[monitor] 从 DB 加载记录失败（首次启动表可能不存在）: {e}')


async def _flush_to_db():
    """批量将 _pending 队列写入 DB"""
    async with _flush_lock:
        to_insert = _pending[:]
        _pending.clear()
    if not to_insert:
        return

    try:
        from ..core.database import get_db_context
        from ..models.entities import MonitorRecord

        async with get_db_context() as session:
            for r in to_insert:
                session.add(MonitorRecord(
                    time=datetime.fromisoformat(r['time']) if isinstance(r['time'], str) else r['time'],
                    feature=r['feature'],
                    input_tokens=r['inputT'],
                    output_tokens=r['outputT'],
                    cost_usd=r['costUSD'],
                    cost_cny=r['costCNY'],
                    latency_ms=r['latencyMs'],
                    from_cache=r['fromCache'],
                    error=r.get('error', False),
                ))
        logger.info(f'[monitor] 持久化了 {len(to_insert)} 条记录到 DB')
    except Exception as e:
        logger.warning(f'[monitor] 持久化失败，记录放回队列: {e}')
        # 失败时放回队列，下次重试
        async with _flush_lock:
            _pending.extend(to_insert)


async def _flush_loop():
    """后台循环：每 30s 批量刷写一次"""
    while True:
        await asyncio.sleep(30)
        try:
            await _flush_to_db()
        except Exception as e:
            logger.warning(f'[monitor] flush 循环异常: {e}')


async def start_flush_task():
    """启动持久化后台任务（由 main.py lifespan 调用）"""
    global _flush_task
    await _load_from_db()
    _flush_task = asyncio.create_task(_flush_loop())
    logger.info('[monitor] 后台持久化任务已启动')


async def stop_flush_task():
    """停止持久化后台任务"""
    global _flush_task
    if _flush_task:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
    # 关闭前最后 flush 一次
    await _flush_to_db()
    logger.info('[monitor] 后台持久化任务已停止')


# ── 统计辅助函数 ───────────────────────────────────────────────

def _percentile(arr, p):
    """计算百分位数"""
    if not arr:
        return 0
    s = sorted(arr)
    idx = max(0, math.ceil(len(s) * p / 100) - 1)
    return s[idx]


def _get_last7_days(calls):
    """计算最近 7 天的统计（用于折线图）"""
    days = []
    for i in range(6, -1, -1):
        d = date.fromordinal(date.today().toordinal() - i)
        day_str = d.isoformat()
        day_calls = [c for c in calls if c['time'][:10] == day_str]
        days.append({
            'date': day_str,
            'label': f'{d.month}/{d.day}',
            'totalCalls': len(day_calls),
            'apiCalls': len([c for c in day_calls if not c['fromCache']]),
            'inputT': sum(c['inputT'] for c in day_calls),
            'outputT': sum(c['outputT'] for c in day_calls),
            'costCNY': round(sum(c['costCNY'] for c in day_calls if not c['fromCache']), 4),
        })
    return days


def _get_by_feature(calls):
    """按功能模块统计调用量、费用、Token"""
    features = {}
    for c in calls:
        f = c['feature']
        if f not in features:
            features[f] = {'calls': 0, 'costCNY': 0, 'tokens': 0}
        features[f]['calls'] += 1
        if not c['fromCache']:
            features[f]['costCNY'] += c['costCNY']
        features[f]['tokens'] += c['inputT'] + c['outputT']

    names = {
        'chat': '对话助手', 'knowledge': 'RAG 知识库', 'agent': '任务 Agent',
        'workflow': '内容工作流', 'erp': 'ERP 审批', 'prompt': 'Prompt 调试',
    }
    return sorted([
        {
            'feature': k,
            'label': names.get(k, k),
            'calls': v['calls'],
            'costCNY': round(v['costCNY'], 4),
            'tokens': v['tokens'],
        }
        for k, v in features.items()
    ], key=lambda x: x['calls'], reverse=True)


# ── API 路由 ──────────────────────────────────────────────────

@monitor_router.get('/stats')
async def get_stats():
    """获取详细统计信息"""
    today_str = date.today().isoformat()
    today_calls = [c for c in _calls if c['time'][:10] == today_str]

    latencies = [c['latencyMs'] for c in today_calls if not c['fromCache'] and c['latencyMs'] > 0]
    total_cost = sum(c['costCNY'] for c in today_calls if not c['fromCache'])
    cache_hits = len([c for c in today_calls if c['fromCache']])
    total_calls = len(today_calls)

    # ── Token 预算自动换算 ─────────────────────────────────────────
    # 加权平均单价（60% 输入 + 40% 输出）：¥1.4016/M tokens
    _AVG_PRICE_CNY_PER_M = (0.14 * 0.6 + 0.28 * 0.4) * 7.2  # ≈ 1.4016

    # ── 模型信息（从配置读取）──────────────────────────────────────
    from ..config import config as app_config
    _model_name = app_config.get('ai', {}).get('primary_model', 'deepseek-chat')
    # 模型名映射（deepseek-chat 已升级到 V4-Flash）
    _MODEL_LABELS = {
        'deepseek-chat': 'DeepSeek V4-Flash',
        'deepseek-reasoner': 'DeepSeek V4-Flash (Thinking)',
        'deepseek-v4-flash': 'DeepSeek V4-Flash',
        'deepseek-v4-pro': 'DeepSeek V4-Pro',
    }

    uptime = (datetime.now() - _start_time).total_seconds()
    token_input_today = sum(c['inputT'] for c in today_calls)
    token_output_today = sum(c['outputT'] for c in today_calls)
    token_budget = round(_daily_budget / _AVG_PRICE_CNY_PER_M * 1e6)
    token_used = token_input_today + token_output_today

    return {
        'overview': {
            'totalCallsToday': total_calls,
            'apiCallsToday': total_calls - cache_hits,
            'cacheHitsToday': cache_hits,
            'cacheHitRate': f'{cache_hits / total_calls * 100:.1f}%' if total_calls else '0%',
            'tokenInputToday': token_input_today,
            'tokenOutputToday': token_output_today,
            'costCNYToday': round(total_cost, 4),
            'dailyBudget': _daily_budget,
            'budgetUsedPct': min(100, math.ceil(total_cost / _daily_budget * 10000) / 100),
            'tokenBudget': token_budget,
            'tokenUsedPct': min(100, math.ceil(token_used / token_budget * 10000) / 100) if token_budget else 0,
            'uptimeSeconds': int(uptime),
            'model': _MODEL_LABELS.get(_model_name, _model_name),
            'pricing': {'input': 0.14, 'output': 0.28, 'unit': 'USD/M'},
        },
        'latency': {
            'p50': _percentile(latencies, 50),
            'p90': _percentile(latencies, 90),
            'p99': _percentile(latencies, 99),
            'avg': round(sum(latencies) / len(latencies)) if latencies else 0,
        },
        'byFeature': _get_by_feature(today_calls),
        'last7Days': _get_last7_days(_calls),
        'recentCalls': [{
            'time': c['time'],
            'feature': c['feature'],
            'inputT': c['inputT'],
            'outputT': c['outputT'],
            'costCNY': round(c['costCNY'], 5),
            'latencyMs': round(c['latencyMs'], 1),
            'fromCache': c['fromCache'],
            'error': c.get('error', False),
        } for c in reversed(_calls[-50:])],
        'cacheStats': cache.get_stats(),
    }


@monitor_router.put('/budget')
async def set_budget(req: BudgetUpdateRequest):
    """设置日预算上限（单位：元），持久化到数据库"""
    global _daily_budget
    budget = req.dailyBudget
    _daily_budget = budget
    from ..services.budget_guard import save_budget
    await save_budget(budget)
    return {'success': True, 'dailyBudget': budget}
