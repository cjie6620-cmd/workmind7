"""
日预算守卫

在 LLM 调用前检查当日费用是否超支。
预算配置持久化到 system_settings 表。
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select

from ..config import config
from ..core.database import async_session_factory
from ..models.entities import MonitorRecord, SystemSetting
from ..utils.logger import logger

BUDGET_SETTING_KEY = 'daily_budget'
DEFAULT_DAILY_BUDGET = 50.0

_memory_budget: float | None = None


async def load_budget() -> float:
    """从 DB 加载日预算，失败时使用默认值"""
    global _memory_budget
    if _memory_budget is not None:
        return _memory_budget

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == BUDGET_SETTING_KEY)
            )
            row = result.scalar_one_or_none()
            if row and 'daily_budget' in row.value:
                _memory_budget = float(row.value['daily_budget'])
                return _memory_budget
    except Exception as e:
        logger.warning(f'[budget] 加载预算失败，使用默认值: {e}')

    _memory_budget = float(config.get('budget', {}).get('daily_budget', DEFAULT_DAILY_BUDGET))
    return _memory_budget


async def save_budget(daily_budget: float) -> None:
    """持久化日预算到 DB"""
    global _memory_budget
    _memory_budget = daily_budget

    from sqlalchemy.dialects.postgresql import insert

    async with async_session_factory() as session:
        stmt = insert(SystemSetting).values(
            key=BUDGET_SETTING_KEY,
            value={'daily_budget': daily_budget},
        ).on_conflict_do_update(
            index_elements=['key'],
            set_={'value': {'daily_budget': daily_budget}},
        )
        await session.execute(stmt)
        await session.commit()


async def get_today_cost_cny() -> float:
    """计算今日已消耗费用（元）"""
    today_str = date.today().isoformat()
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(MonitorRecord))
            rows = result.scalars().all()
            return sum(
                r.cost_cny for r in rows
                if r.time and r.time.date().isoformat() == today_str and not r.from_cache
            )
    except Exception:
        from ..routes.monitor import _calls
        return sum(
            c['costCNY'] for c in _calls
            if c['time'][:10] == today_str and not c['fromCache']
        )


async def check_budget_before_llm() -> None:
    """
    检查预算是否超支

    BUDGET_ENFORCE=true 时超支抛出 402；否则仅 WARN 日志。
    """
    daily_budget = await load_budget()
    today_cost = await get_today_cost_cny()
    used_pct = (today_cost / daily_budget * 100) if daily_budget > 0 else 0

    if used_pct >= 100:
        msg = f'日预算已用尽（{today_cost:.2f}/{daily_budget:.2f} 元）'
        enforce = config.get('budget', {}).get('enforce', False)
        if enforce:
            raise HTTPException(
                status_code=402,
                detail={'error': {'code': 'BUDGET_EXCEEDED', 'message': msg}},
            )
        logger.warning(f'[budget] {msg}（BUDGET_ENFORCE=false，仅告警）')
