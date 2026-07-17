"""监控价格、SQL 聚合与 Redis 预算预留的生产契约测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_openai import ChatOpenAI
from sqlalchemy.dialects import postgresql

from app.routes import monitor
from app.services import budget_guard, interceptor
from app.services.budget_guard import BudgetReservation
from app.services.pricing import calculate_token_cost, get_pricing
from app.utils.business_time import (
    business_date,
    business_day_utc_bounds,
    seconds_until_business_day_end,
)


class _MappingRows:
    def __init__(self, rows):
        self._rows = rows

    def one(self):
        assert len(self._rows) == 1
        return self._rows[0]

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return _MappingRows(self._rows)

    def scalar_one(self):
        return self._scalar


class _AsyncSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _AtomicRedisLedger:
    """用 asyncio.Lock 模拟 Redis 单线程执行 Lua 的原子语义。"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.total: float | None = None
        self.reservations: dict[str, float] = {}

    async def eval(self, script, keys, args):
        del keys
        async with self.lock:
            if script == budget_guard._RESERVE_SCRIPT:
                reservation_id, amount, budget, _, baseline, enforce = args
                if self.total is None:
                    if baseline == "":
                        return ["NEEDS_BASELINE", "0"]
                    self.total = float(baseline)
                if reservation_id in self.reservations:
                    return ["RESERVED", str(self.total)]
                requested = float(amount)
                if enforce == "1" and self.total + requested > float(budget):
                    return ["REJECTED", str(self.total)]
                self.reservations[reservation_id] = requested
                self.total += requested
                return ["RESERVED", str(self.total)]

            if script == budget_guard._SETTLE_SCRIPT:
                reservation_id, actual, _ = args
                reserved = self.reservations.pop(reservation_id, None)
                if reserved is None:
                    return ["MISSING", str(self.total or 0)]
                if actual != "":
                    self.total = max(0.0, (self.total or 0) + float(actual) - reserved)
                return ["SETTLED", str(self.total)]

            raise AssertionError("unexpected Lua script")


def _reservation(reserved_cny: float = 0.5) -> BudgetReservation:
    return BudgetReservation(
        reservation_id="reservation-1",
        ledger_key="workmind:budget:total:2026-07-16",
        reservations_key="workmind:budget:reservations:2026-07-16",
        reserved_cny=reserved_cny,
        estimated_input_tokens=100,
        reserved_output_tokens=1_000,
        model_name="deepseek-chat",
    )


def test_pricing_uses_single_environment_configuration(monkeypatch):
    monkeypatch.setenv("LLM_INPUT_PRICE_USD_PER_MILLION", "0.25")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_USD_PER_MILLION", "1.00")
    monkeypatch.setenv("USD_CNY_EXCHANGE_RATE", "7.00")
    monkeypatch.setenv("LLM_BUDGET_MAX_OUTPUT_TOKENS", "4096")

    pricing = get_pricing("deepseek-chat")
    cost = calculate_token_cost(1_000_000, 500_000, pricing=pricing)

    assert pricing.model_name == "deepseek-chat"
    assert pricing.source == "configured"
    assert pricing.max_output_tokens == 4096
    assert cost.usd == pytest.approx(0.75)
    assert cost.cny == pytest.approx(5.25)


def test_empty_usage_metadata_is_not_treated_as_zero_cost():
    assert interceptor._extract_token_usage(SimpleNamespace(usage_metadata={})) == (
        0,
        0,
        False,
    )


def test_business_day_boundaries_and_ledger_ttl_use_configured_timezone(monkeypatch):
    monkeypatch.setitem(budget_guard.config["app"], "business_timezone", "Asia/Shanghai")

    assert business_date(datetime(2026, 7, 15, 16, 0)) == date(2026, 7, 16)
    assert business_day_utc_bounds(date(2026, 7, 16)) == (
        datetime(2026, 7, 15, 16, 0),
        datetime(2026, 7, 16, 16, 0),
    )
    assert (
        seconds_until_business_day_end(
            date(2026, 7, 16),
            now_utc=datetime(2026, 7, 16, 15, 59, 30),
        )
        == 30
    )
    assert (
        budget_guard._ledger_ttl_seconds(
            date(2026, 7, 16),
            now_utc=datetime(2026, 7, 16, 15, 59, 30),
        )
        == 3_630
    )


def test_business_day_bounds_respect_dst(monkeypatch):
    monkeypatch.setitem(budget_guard.config["app"], "business_timezone", "America/New_York")

    start, end = business_day_utc_bounds(date(2026, 3, 8))

    assert start == datetime(2026, 3, 8, 5, 0)
    assert end == datetime(2026, 3, 9, 4, 0)
    assert end - start == timedelta(hours=23)


def test_monitor_memory_grouping_and_recent_display_use_business_timezone(monkeypatch):
    monkeypatch.setitem(budget_guard.config["app"], "business_timezone", "Asia/Shanghai")
    calls = [
        {
            "time": "2026-07-15T15:59:59",
            "feature": "chat",
            "inputT": 1,
            "outputT": 2,
            "costCNY": 0.1,
            "latencyMs": 10,
            "fromCache": False,
        },
        {
            "time": "2026-07-15T16:00:00",
            "feature": "chat",
            "inputT": 3,
            "outputT": 4,
            "costCNY": 0.2,
            "latencyMs": 20,
            "fromCache": False,
        },
    ]

    last7 = monitor._get_last7_days(calls, date(2026, 7, 16))
    recent = monitor._format_recent_rows(
        [
            {
                "time": datetime(2026, 7, 15, 16, 30),
                "feature": "chat",
                "input_tokens": 3,
                "output_tokens": 4,
                "cost_cny": 0.2,
                "latency_ms": 20,
                "from_cache": False,
                "error": False,
            }
        ]
    )

    assert last7[-2]["date"] == "2026-07-15"
    assert last7[-2]["totalCalls"] == 1
    assert last7[-1]["date"] == "2026-07-16"
    assert last7[-1]["totalCalls"] == 1
    assert recent[0]["time"] == "2026-07-16T00:30:00+08:00"


@pytest.mark.asyncio
async def test_monitor_queries_bounded_sql_aggregates(monkeypatch):
    today_row = {
        "total_calls": 3,
        "api_calls": 2,
        "cache_hits": 1,
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_cny": 0.25,
        "p50": 10.0,
        "p90": 20.0,
        "p99": 30.0,
        "avg_latency": 15.0,
    }
    results = [
        _Result([today_row]),
        _Result(
            [
                {
                    "day": date(2026, 7, 16),
                    "total_calls": 3,
                    "api_calls": 2,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_cny": 0.25,
                }
            ]
        ),
        _Result([{"feature": "chat", "calls": 3, "cost_cny": 0.25, "tokens": 150}]),
        _Result(
            [
                {
                    "time": datetime(2026, 7, 16, 10, 0),
                    "feature": "chat",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_cny": 0.25,
                    "latency_ms": 15,
                    "from_cache": False,
                    "error": False,
                }
            ]
        ),
    ]
    session = SimpleNamespace(execute=AsyncMock(side_effect=results))

    import app.core.database as database

    monkeypatch.setattr(
        database,
        "async_session_factory",
        lambda: _AsyncSessionContext(session),
    )

    stats = await monitor._query_stats_from_db(date(2026, 7, 16))
    statements = [call.args[0] for call in session.execute.await_args_list]
    today_sql = str(statements[0]).lower()
    last7_sql = str(statements[1]).lower()
    compiled_last7_sql = str(
        statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    feature_sql = str(statements[2]).lower()
    recent_sql = str(statements[3]).lower()
    today_params = statements[0].compile().params.values()

    assert stats["today"]["total_calls"] == 3
    assert "percentile_cont" in today_sql
    assert "monitor_records.time >=" in today_sql
    assert "monitor_records.time <" in today_sql
    assert "group by" in last7_sql
    assert "timezone" in last7_sql
    assert "timezone('asia/shanghai', timezone('utc', monitor_records.time))" in compiled_last7_sql
    assert "monitor_records.time >=" in last7_sql
    assert "group by monitor_records.feature" in feature_sql
    assert "limit" in recent_sql
    assert datetime(2026, 7, 15, 16, 0) in today_params
    assert datetime(2026, 7, 16, 16, 0) in today_params


@pytest.mark.asyncio
async def test_monitor_stats_exposes_configured_pricing_source(monkeypatch):
    monkeypatch.setitem(budget_guard.config["ai"], "primary_model", "deepseek-chat")
    monkeypatch.setenv("LLM_INPUT_PRICE_USD_PER_MILLION", "0.20")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_USD_PER_MILLION", "0.80")
    monkeypatch.setenv("USD_CNY_EXCHANGE_RATE", "7.10")
    monkeypatch.setattr(monitor, "_flush_to_db", AsyncMock())
    monkeypatch.setattr(
        monitor,
        "_query_stats_from_db",
        AsyncMock(
            return_value={
                "today": {
                    "total_calls": 0,
                    "api_calls": 0,
                    "cache_hits": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_cny": 0,
                    "p50": 0,
                    "p90": 0,
                    "p99": 0,
                    "avg_latency": 0,
                },
                "last7": [],
                "features": [],
                "recent": [],
            }
        ),
    )
    monkeypatch.setattr(budget_guard, "load_budget", AsyncMock(return_value=50.0))

    stats = await monitor.get_stats()

    pricing = stats["overview"]["pricing"]
    assert stats["overview"]["statsSource"] == "database"
    assert pricing == {
        "input": 0.2,
        "output": 0.8,
        "unit": "USD/M",
        "exchangeRate": 7.1,
        "pricingModel": "deepseek-chat",
        "source": "configured",
    }


@pytest.mark.asyncio
async def test_budget_cost_uses_bounded_sum_query(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result(scalar=12.5)))
    monkeypatch.setattr(
        budget_guard,
        "async_session_factory",
        lambda: _AsyncSessionContext(session),
    )
    monkeypatch.setitem(budget_guard.config["budget"], "enforce", False)

    cost = await budget_guard.get_today_cost_cny(date(2026, 7, 16))
    statement = session.execute.await_args.args[0]
    sql = str(statement).lower()
    query_params = statement.compile().params.values()

    assert cost == pytest.approx(12.5)
    assert "sum(monitor_records.cost_cny)" in sql
    assert "monitor_records.time >=" in sql
    assert "monitor_records.time <" in sql
    assert "monitor_records.from_cache is false" in sql
    assert datetime(2026, 7, 15, 16, 0) in query_params
    assert datetime(2026, 7, 16, 16, 0) in query_params


@pytest.mark.asyncio
async def test_budget_memory_fallback_filters_by_business_day(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(
        budget_guard,
        "async_session_factory",
        lambda: _AsyncSessionContext(session),
    )
    monkeypatch.setitem(budget_guard.config["budget"], "enforce", False)
    monkeypatch.setitem(budget_guard.config["app"], "business_timezone", "Asia/Shanghai")
    monkeypatch.setattr(
        monitor,
        "_calls",
        [
            {
                "time": "2026-07-15T15:59:59",
                "costCNY": 1.0,
                "fromCache": False,
            },
            {
                "time": "2026-07-15T16:00:00",
                "costCNY": 2.0,
                "fromCache": False,
            },
        ],
    )

    cost = await budget_guard.get_today_cost_cny(date(2026, 7, 16))

    assert cost == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_concurrent_reservations_are_atomic(monkeypatch):
    ledger = _AtomicRedisLedger()
    monkeypatch.setattr(budget_guard, "load_budget", AsyncMock(return_value=1.0))
    monkeypatch.setattr(budget_guard, "get_today_cost_cny", AsyncMock(return_value=0.0))
    monkeypatch.setattr(budget_guard, "_redis_eval", ledger.eval)
    monkeypatch.setitem(budget_guard.config["budget"], "enforce", True)

    async def reserve():
        return await budget_guard._reserve_amount(
            reserved_cny=0.26,
            estimated_input_tokens=100,
            reserved_output_tokens=1_000,
            model_name="deepseek-chat",
            target_day=date(2026, 7, 16),
        )

    results = await asyncio.gather(*(reserve() for _ in range(10)), return_exceptions=True)
    accepted = [result for result in results if isinstance(result, BudgetReservation)]
    rejected = [result for result in results if isinstance(result, HTTPException)]

    assert len(accepted) == 3
    assert len(rejected) == 7
    assert all(error.status_code == 402 for error in rejected)
    assert ledger.total == pytest.approx(0.78)
    assert len(ledger.reservations) == 3


@pytest.mark.asyncio
async def test_reservation_settlement_is_idempotent_and_unknown_usage_is_conservative(
    monkeypatch,
):
    ledger = _AtomicRedisLedger()
    ledger.total = 0.5
    ledger.reservations["reservation-1"] = 0.5
    monkeypatch.setattr(budget_guard, "_redis_eval", ledger.eval)

    reservation = _reservation()
    assert await budget_guard.settle_budget_reservation(reservation, 0.2) is True
    assert ledger.total == pytest.approx(0.2)
    assert await budget_guard.settle_budget_reservation(reservation, 0.2) is False
    assert ledger.total == pytest.approx(0.2)

    ledger.total = 0.7
    ledger.reservations["reservation-2"] = 0.5
    unknown_usage = replace(reservation, reservation_id="reservation-2")
    assert await budget_guard.settle_budget_reservation(unknown_usage, None) is True
    assert ledger.total == pytest.approx(0.7)
    assert "reservation-2" not in ledger.reservations


@pytest.mark.asyncio
async def test_redis_failure_is_closed_when_enforced_and_explicitly_degraded_otherwise(
    monkeypatch,
):
    monkeypatch.setattr(budget_guard, "load_budget", AsyncMock(return_value=1.0))

    async def unavailable(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(budget_guard, "_redis_eval", unavailable)
    monkeypatch.setitem(budget_guard.config["budget"], "enforce", True)

    with pytest.raises(HTTPException) as error:
        await budget_guard._reserve_amount(
            reserved_cny=0.1,
            estimated_input_tokens=10,
            reserved_output_tokens=100,
            model_name="deepseek-chat",
        )
    assert error.value.status_code == 503
    assert error.value.detail["error"]["code"] == "BUDGET_GUARD_UNAVAILABLE"

    monkeypatch.setitem(budget_guard.config["budget"], "enforce", False)
    reservation = await budget_guard._reserve_amount(
        reserved_cny=0.1,
        estimated_input_tokens=10,
        reserved_output_tokens=100,
        model_name="deepseek-chat",
    )
    assert reservation.redis_accounted is False
    assert reservation.reservation_id is None


@pytest.mark.asyncio
async def test_interceptor_reserves_and_settles_ainvoke(monkeypatch):
    reservation = _reservation()
    reserve = AsyncMock(return_value=reservation)
    settle = AsyncMock()
    record = MagicMock()

    async def provider_ainvoke(self, input_value, config=None, **kwargs):
        del self, input_value, config, kwargs
        return SimpleNamespace(
            content="ok",
            usage_metadata={"input_tokens": 120, "output_tokens": 30},
        )

    monkeypatch.setattr(ChatOpenAI, "ainvoke", provider_ainvoke)
    monkeypatch.setattr(budget_guard, "reserve_budget_before_llm", reserve)
    monkeypatch.setattr(budget_guard, "settle_budget_after_llm", settle)
    monkeypatch.setattr(interceptor, "_record_api_call", record)
    fixed_started_at = datetime(2026, 7, 16, 16, 0)
    monkeypatch.setattr(interceptor, "utc_now_naive", lambda: fixed_started_at)

    model = interceptor.MonitoredChatOpenAI(
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://example.invalid",
    )
    result = await model.ainvoke(["hello"], max_tokens=500)

    assert result.content == "ok"
    reserve.assert_awaited_once_with(
        ["hello"],
        model_name="deepseek-chat",
        max_output_tokens=500,
        target_day=date(2026, 7, 17),
    )
    settle.assert_awaited_once_with(
        reservation,
        120,
        30,
        usage_known=True,
    )
    assert record.call_args.kwargs["model_name"] == "deepseek-chat"
    assert record.call_args.kwargs["started_at"] == fixed_started_at


@pytest.mark.asyncio
async def test_interceptor_stream_unknown_usage_keeps_conservative_reservation(
    monkeypatch,
):
    reservation = _reservation()
    reserve = AsyncMock(return_value=reservation)
    settle = AsyncMock()

    async def provider_astream(self, input_value, config=None, **kwargs):
        del self, input_value, config, kwargs
        yield SimpleNamespace(content="a", usage_metadata=None)
        yield SimpleNamespace(content="b", usage_metadata=None)

    monkeypatch.setattr(ChatOpenAI, "astream", provider_astream)
    monkeypatch.setattr(budget_guard, "reserve_budget_before_llm", reserve)
    monkeypatch.setattr(budget_guard, "settle_budget_after_llm", settle)
    monkeypatch.setattr(interceptor, "_record_api_call", MagicMock())

    model = interceptor.MonitoredChatOpenAI(
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://example.invalid",
    )
    chunks = [chunk async for chunk in model.astream(["hello"])]

    assert [chunk.content for chunk in chunks] == ["a", "b"]
    settle.assert_awaited_once_with(
        reservation,
        0,
        0,
        usage_known=False,
    )


def test_interceptor_invoke_is_disabled():
    model = interceptor.MonitoredChatOpenAI(
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://example.invalid",
    )
    with pytest.raises(RuntimeError, match="绕过预算守卫"):
        model.invoke(["hello"])
