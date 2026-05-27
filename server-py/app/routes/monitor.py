"""
用量监控路由模块

提供 API 调用统计和成本分析：
- GET /stats: 获取详细统计信息
- PUT /budget: 设置日预算上限

统计维度：
- 今日调用量、API 调用量、缓存命中量
- Token 消耗（输入/输出）
- 费用统计（今日、近7天、按功能模块）
- 延迟统计（P50/P90/P99）
- 最近 50 条调用记录
"""

import json
import math
from datetime import datetime, date

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..services.cache import cache
from ..utils.logger import logger

monitor_router = APIRouter()

# 服务启动时间
_start_time = datetime.now()

# 调用记录存储（内存，生产环境建议用数据库）
# 结构：{ time, feature, inputT, outputT, costCNY, fromCache, latencyMs }
_calls = []

# 日预算上限（单位：元）
_daily_budget = 50


def record_api_call(feature='chat', input_tokens=0, output_tokens=0, latency_ms=0, from_cache=False, error=False):
    """
    记录一次 API 调用

    自动计算费用：
    - 输入：$0.27/M tokens
    - 输出：$1.10/M tokens
    - 汇率：7.2
    """
    cost_usd = (input_tokens / 1e6 * 0.27) + (output_tokens / 1e6 * 1.10)
    _calls.append({
        'time': datetime.now().isoformat(),
        'feature': feature,
        'inputT': input_tokens,
        'outputT': output_tokens,
        'costUSD': cost_usd,
        'costCNY': cost_usd * 7.2,
        'latencyMs': latency_ms,
        'fromCache': from_cache,
        'error': error,
    })
    # 保留最近 500 条记录
    if len(_calls) > 500:
        _calls.pop(0)


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

    # 功能模块名称映射
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


@monitor_router.get('/stats')
async def get_stats():
    """
    获取详细统计信息

    返回：
    - overview: 概览（调用量、Token、费用、缓存命中率、预算使用率）
    - latency: 延迟统计（P50/P90/P99/平均）
    - byFeature: 按功能模块统计
    - last7Days: 近7天趋势
    - recentCalls: 最近 50 条记录
    - cacheStats: 缓存统计
    """
    today_str = date.today().isoformat()
    today_calls = [c for c in _calls if c['time'][:10] == today_str]

    # 统计今日延迟（排除缓存命中）
    latencies = [c['latencyMs'] for c in today_calls if not c['fromCache'] and c['latencyMs'] > 0]
    total_cost = sum(c['costCNY'] for c in today_calls if not c['fromCache'])
    cache_hits = len([c for c in today_calls if c['fromCache']])
    total_calls = len(today_calls)

    uptime = (datetime.now() - _start_time).total_seconds()

    return {
        'overview': {
            'totalCallsToday': total_calls,
            'apiCallsToday': total_calls - cache_hits,
            'cacheHitsToday': cache_hits,
            'cacheHitRate': f'{cache_hits / total_calls * 100:.1f}%' if total_calls else '0%',
            'tokenInputToday': sum(c['inputT'] for c in today_calls),
            'tokenOutputToday': sum(c['outputT'] for c in today_calls),
            'costCNYToday': round(total_cost, 4),
            'dailyBudget': _daily_budget,
            'budgetUsedPct': min(100, round(total_cost / _daily_budget * 100, 1)),
            'uptimeSeconds': int(uptime),
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
            'latencyMs': c['latencyMs'],
            'fromCache': c['fromCache'],
        } for c in reversed(_calls[-50:])],
        'cacheStats': cache.get_stats(),
    }


@monitor_router.put('/budget')
async def set_budget(req: dict):
    """设置日预算上限（单位：元）"""
    global _daily_budget
    budget = req.get('dailyBudget')
    if not isinstance(budget, (int, float)) or budget <= 0:
        return JSONResponse(status_code=400, content={'error': {'message': '预算必须是正数'}})
    _daily_budget = budget
    return {'success': True, 'dailyBudget': budget}