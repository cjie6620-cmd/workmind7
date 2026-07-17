"""
日预算守卫。

Redis 日累计是运行时预算账本，PostgreSQL 监控记录仅用于当天首次初始化。
请求前通过 Lua 原子预留保守额度，调用后按实际 token 结算；多 worker 共享同一账本。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from ..config import config
from ..core.database import async_session_factory
from ..core.redis_client import get_redis
from ..models.entities import MonitorRecord, SystemSetting
from ..utils.business_time import (
    business_date,
    business_day_utc_bounds,
    seconds_until_business_day_end,
)
from ..utils.logger import logger
from .pricing import calculate_reservation_cost, calculate_token_cost


BUDGET_SETTING_KEY = "daily_budget"
DEFAULT_DAILY_BUDGET = 50.0
BUDGET_REDIS_PREFIX = "workmind:budget"
BUDGET_KEY_GRACE_SECONDS = 3_600

_memory_budget: float | None = None


_RESERVE_SCRIPT = """
local current_raw = redis.call('GET', KEYS[1])
if not current_raw then
    if ARGV[5] == '' then
        return {'NEEDS_BASELINE', '0'}
    end
    current_raw = ARGV[5]
    redis.call('SET', KEYS[1], current_raw, 'EX', ARGV[4])
end

local current = tonumber(current_raw) or 0
local existing = redis.call('HGET', KEYS[2], ARGV[1])
if existing then
    return {'RESERVED', tostring(current)}
end

local requested = tonumber(ARGV[2]) or 0
local budget = tonumber(ARGV[3]) or 0
local enforce = ARGV[6] == '1'
if enforce and (budget <= 0 or current + requested > budget) then
    return {'REJECTED', tostring(current)}
end

redis.call('HSET', KEYS[2], ARGV[1], tostring(requested))
local updated = redis.call('INCRBYFLOAT', KEYS[1], requested)
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return {'RESERVED', tostring(updated)}
"""


_SETTLE_SCRIPT = """
local reserved_raw = redis.call('HGET', KEYS[2], ARGV[1])
if not reserved_raw then
    return {'MISSING', redis.call('GET', KEYS[1]) or '0'}
end

local reserved = tonumber(reserved_raw) or 0
local updated
if ARGV[2] == '' then
    updated = tonumber(redis.call('GET', KEYS[1]) or '0')
else
    local actual = tonumber(ARGV[2]) or 0
    updated = redis.call('INCRBYFLOAT', KEYS[1], actual - reserved)
    if tonumber(updated) < 0 then
        redis.call('SET', KEYS[1], '0', 'EX', ARGV[3])
        updated = '0'
    end
end

redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return {'SETTLED', tostring(updated)}
"""


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    """一次 LLM 调用的预算预留凭据。"""

    reservation_id: str | None
    ledger_key: str
    reservations_key: str
    reserved_cny: float
    estimated_input_tokens: int
    reserved_output_tokens: int
    model_name: str
    redis_accounted: bool = True


def _is_enforced() -> bool:
    return bool(config.get("budget", {}).get("enforce", False))


def _day_bounds(target_day: date) -> tuple[datetime, datetime]:
    return business_day_utc_bounds(target_day)


def _ledger_keys(target_day: date) -> tuple[str, str]:
    day_key = target_day.isoformat()
    return (
        f"{BUDGET_REDIS_PREFIX}:total:{day_key}",
        f"{BUDGET_REDIS_PREFIX}:reservations:{day_key}",
    )


def _ledger_ttl_seconds(
    target_day: date,
    *,
    now_utc: datetime | None = None,
) -> int:
    seconds_until_day_end = seconds_until_business_day_end(
        target_day,
        now_utc=now_utc,
    )
    return max(60, seconds_until_day_end + BUDGET_KEY_GRACE_SECONDS)


def _guard_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": {
                "code": "BUDGET_GUARD_UNAVAILABLE",
                "message": message,
            }
        },
    )


def _budget_exceeded(today_cost: float, daily_budget: float) -> HTTPException:
    return HTTPException(
        status_code=402,
        detail={
            "error": {
                "code": "BUDGET_EXCEEDED",
                "message": f"日预算不足（已计入预留 {today_cost:.4f}/{daily_budget:.4f} 元）",
            }
        },
    )


async def _redis_eval(script: str, keys: tuple[str, ...], args: tuple[str, ...]):
    """在线程池执行同步 redis-py，避免阻塞 FastAPI 事件循环。"""
    client = get_redis()
    return await asyncio.to_thread(client.eval, script, len(keys), *keys, *args)


def _decode_script_result(result: Any) -> tuple[str, float]:
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise RuntimeError(f"unexpected Redis budget result: {result!r}")
    status = result[0].decode() if isinstance(result[0], bytes) else str(result[0])
    raw_total = result[1].decode() if isinstance(result[1], bytes) else str(result[1])
    return status, float(raw_total)


async def load_budget() -> float:
    """
    从数据库读取日预算。

    每次读取主键行，避免 worker 本地缓存导致管理员更新后各进程预算不一致。
    非强制模式下数据库故障才会显式降级到进程内最近值或环境默认值。
    """
    global _memory_budget

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(SystemSetting).where(SystemSetting.key == BUDGET_SETTING_KEY))
            row = result.scalar_one_or_none()
            if row and "daily_budget" in row.value:
                _memory_budget = float(row.value["daily_budget"])
                return _memory_budget
    except Exception as exc:
        if _is_enforced():
            logger.error(f"[budget] 预算配置数据库不可用，强制模式拒绝 LLM 调用: {exc}")
            raise _guard_unavailable("预算配置暂时不可用，请稍后重试") from exc
        logger.warn(f"[budget] 预算配置数据库不可用，降级使用最近配置: {exc}")

    if _memory_budget is None:
        _memory_budget = float(config.get("budget", {}).get("daily_budget", DEFAULT_DAILY_BUDGET))
    return _memory_budget


async def save_budget(daily_budget: float) -> None:
    """持久化日预算到数据库；所有 worker 下一次调用均读取新值。"""
    global _memory_budget

    from sqlalchemy.dialects.postgresql import insert

    async with async_session_factory() as session:
        stmt = (
            insert(SystemSetting)
            .values(
                key=BUDGET_SETTING_KEY,
                value={"daily_budget": daily_budget},
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": {"daily_budget": daily_budget}},
            )
        )
        await session.execute(stmt)
        await session.commit()
    _memory_budget = daily_budget


async def get_today_cost_cny(target_day: date | None = None) -> float:
    """使用有界 SQL 聚合指定日期的已持久化实际费用。"""
    selected_day = target_day or business_date()
    day_start, day_end = _day_bounds(selected_day)

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(MonitorRecord.cost_cny), 0.0)).where(
                    MonitorRecord.time >= day_start,
                    MonitorRecord.time < day_end,
                    MonitorRecord.from_cache.is_(False),
                )
            )
            return float(result.scalar_one())
    except Exception as exc:
        if _is_enforced():
            logger.error(f"[budget] 当日费用聚合失败，强制模式拒绝初始化预算账本: {exc}")
            raise _guard_unavailable("预算用量暂时不可用，请稍后重试") from exc

        # 非强制模式明确降级，仅统计本 worker 尚可见的内存记录。
        from ..routes.monitor import _calls

        logger.warn(f"[budget] 当日费用聚合失败，降级使用本进程监控记录: {exc}")
        return sum(
            float(call["costCNY"])
            for call in _calls
            if business_date(call["time"]) == selected_day and not call["fromCache"]
        )


async def _reserve_amount(
    *,
    reserved_cny: float,
    estimated_input_tokens: int,
    reserved_output_tokens: int,
    model_name: str,
    target_day: date | None = None,
) -> BudgetReservation:
    selected_day = target_day or business_date()
    ledger_key, reservations_key = _ledger_keys(selected_day)
    ttl_seconds = _ledger_ttl_seconds(selected_day)
    reservation_id = uuid4().hex
    daily_budget = await load_budget()
    enforce = _is_enforced()

    def build_args(baseline: str) -> tuple[str, ...]:
        return (
            reservation_id,
            f"{reserved_cny:.12f}",
            f"{daily_budget:.12f}",
            str(ttl_seconds),
            baseline,
            "1" if enforce else "0",
        )

    try:
        result = await _redis_eval(
            _RESERVE_SCRIPT,
            (ledger_key, reservations_key),
            build_args(""),
        )
        status, accounted_total = _decode_script_result(result)

        if status == "NEEDS_BASELINE":
            baseline = await get_today_cost_cny(selected_day)
            result = await _redis_eval(
                _RESERVE_SCRIPT,
                (ledger_key, reservations_key),
                build_args(f"{baseline:.12f}"),
            )
            status, accounted_total = _decode_script_result(result)
    except HTTPException:
        raise
    except Exception as exc:
        if enforce:
            logger.error(f"[budget] Redis 原子预留失败，强制模式拒绝 LLM 调用: {exc}")
            raise _guard_unavailable("预算守卫暂时不可用，请稍后重试") from exc

        logger.warn(f"[budget] Redis 原子预留失败，BUDGET_ENFORCE=false，降级放行: {exc}")
        return BudgetReservation(
            reservation_id=None,
            ledger_key=ledger_key,
            reservations_key=reservations_key,
            reserved_cny=reserved_cny,
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            model_name=model_name,
            redis_accounted=False,
        )

    if status == "REJECTED":
        raise _budget_exceeded(accounted_total, daily_budget)
    if status != "RESERVED":
        if enforce:
            raise _guard_unavailable("预算守卫返回了无效状态")
        logger.warn(f"[budget] Redis 返回未知状态 {status}，非强制模式降级放行")
        return BudgetReservation(
            reservation_id=None,
            ledger_key=ledger_key,
            reservations_key=reservations_key,
            reserved_cny=reserved_cny,
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            model_name=model_name,
            redis_accounted=False,
        )

    if not enforce and accounted_total > daily_budget:
        logger.warn(
            f"[budget] 日预算已超出（含预留 {accounted_total:.4f}/{daily_budget:.4f} 元），"
            "BUDGET_ENFORCE=false，继续记录但不拦截"
        )

    return BudgetReservation(
        reservation_id=reservation_id,
        ledger_key=ledger_key,
        reservations_key=reservations_key,
        reserved_cny=reserved_cny,
        estimated_input_tokens=estimated_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        model_name=model_name,
    )


async def reserve_budget_before_llm(
    input_value: Any,
    *,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
    target_day: date | None = None,
) -> BudgetReservation:
    """根据输入与最大输出 token，在调用模型前原子预留保守费用。"""
    cost, estimated_input, reserved_output, pricing = calculate_reservation_cost(
        input_value,
        model_name=model_name,
        max_output_tokens=max_output_tokens,
    )
    return await _reserve_amount(
        reserved_cny=cost.cny,
        estimated_input_tokens=estimated_input,
        reserved_output_tokens=reserved_output,
        model_name=pricing.model_name,
        target_day=target_day,
    )


async def settle_budget_reservation(
    reservation: BudgetReservation,
    actual_cost_cny: float | None,
) -> bool:
    """
    幂等结算预留。

    actual_cost_cny 为 None（调用中断或供应商未返回 usage）时保留整笔预留，
    进程在结算前崩溃也采用相同策略；总高估上限为受影响请求预留额之和，且账本次日过期。
    若实际费用高于预留，超支误差上限为所有并发请求的 (actual - reserved) 正差之和。
    """
    if not reservation.redis_accounted or reservation.reservation_id is None:
        return False

    ttl_seconds = _ledger_ttl_seconds(date.fromisoformat(reservation.ledger_key.rsplit(":", 1)[-1]))
    actual_arg = "" if actual_cost_cny is None else f"{actual_cost_cny:.12f}"
    try:
        result = await _redis_eval(
            _SETTLE_SCRIPT,
            (reservation.ledger_key, reservation.reservations_key),
            (reservation.reservation_id, actual_arg, str(ttl_seconds)),
        )
        status, _ = _decode_script_result(result)
    except Exception as exc:
        # 结算失败不向客户端抛错：Redis 中仍保留保守预留，避免用户重试造成重复消费。
        logger.error(f"[budget] Redis 结算失败，保留原预留额度: {exc}")
        return False

    if status == "MISSING":
        logger.warn(f"[budget] 预留已结算或不存在: {reservation.reservation_id}")
        return False
    if status != "SETTLED":
        logger.error(f"[budget] Redis 结算返回未知状态: {status}")
        return False

    if actual_cost_cny is not None and actual_cost_cny > reservation.reserved_cny:
        logger.warn(
            "[budget] 实际费用超过保守预留，请调高 LLM_BUDGET_MAX_OUTPUT_TOKENS；"
            f"actual={actual_cost_cny:.6f}, reserved={reservation.reserved_cny:.6f}"
        )
    return True


async def settle_budget_after_llm(
    reservation: BudgetReservation,
    input_tokens: int,
    output_tokens: int,
    *,
    usage_known: bool,
) -> None:
    """按供应商 usage 结算；usage 缺失时保留保守预留。"""
    actual_cost = None
    if usage_known:
        actual_cost = calculate_token_cost(
            input_tokens,
            output_tokens,
            model_name=reservation.model_name,
        ).cny
    await settle_budget_reservation(reservation, actual_cost)


async def check_budget_before_llm(
    input_value: Any = None,
    *,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
    target_day: date | None = None,
) -> BudgetReservation:
    """兼容旧调用名，返回必须在调用结束后结算的预留凭据。"""
    return await reserve_budget_before_llm(
        input_value,
        model_name=model_name,
        max_output_tokens=max_output_tokens,
        target_day=target_day,
    )
