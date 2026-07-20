"""
用量监控路由（admin）

只做 HTTP 协议层；记录、持久化管线与统计聚合全部在 services/usage_monitor.py：
- GET /stats: 详细统计（数据库有界聚合，失败降级内存）
- PUT /budget: 设置日预算上限（持久化到 system_settings）
"""

from fastapi import APIRouter

from ..schemas.requests import BudgetUpdateRequest
from ..services.usage_monitor import build_stats_payload, update_daily_budget

monitor_router = APIRouter()


@monitor_router.get("/stats")
async def get_stats():
    """获取详细统计信息"""
    return await build_stats_payload()


@monitor_router.put("/budget")
async def set_budget(req: BudgetUpdateRequest):
    """设置日预算上限（单位：元），持久化到数据库"""
    await update_daily_budget(req.dailyBudget)
    return {"success": True, "dailyBudget": req.dailyBudget}
