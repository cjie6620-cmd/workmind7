"""业务时区与数据库 UTC-naive 时间之间的统一转换。"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from ..config import config


UTC = timezone.utc


def business_timezone_name() -> str:
    """返回已配置的 IANA 业务时区名称。"""
    return str(config["app"]["business_timezone"])


@lru_cache(maxsize=16)
def _zoneinfo(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def business_timezone() -> ZoneInfo:
    """返回业务时区；配置合法性由启动校验保证。"""
    return _zoneinfo(business_timezone_name())


def utc_now_naive() -> datetime:
    """返回符合数据库约定的 UTC-naive 当前时间。"""
    return datetime.now(UTC).replace(tzinfo=None)


def business_now() -> datetime:
    """返回带 IANA 时区偏移的当前业务时间。"""
    return datetime.now(UTC).astimezone(business_timezone())


def to_utc_naive(value: datetime) -> datetime:
    """将时间归一为 UTC-naive；naive 输入按数据库约定视为 UTC。"""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def parse_utc_naive(value: datetime | str) -> datetime:
    """解析数据库或内存记录，并归一为 UTC-naive。"""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return to_utc_naive(parsed)


def to_business_datetime(value: datetime | str) -> datetime:
    """将 UTC-naive 数据库时间转换为带偏移的业务时间。"""
    utc_value = parse_utc_naive(value).replace(tzinfo=UTC)
    return utc_value.astimezone(business_timezone())


def business_date(value: datetime | str | None = None) -> date:
    """返回给定 UTC 时刻所属的业务日期。"""
    candidate = utc_now_naive() if value is None else value
    return to_business_datetime(candidate).date()


def business_day_utc_bounds(target_day: date) -> tuple[datetime, datetime]:
    """返回业务日对应的 ``[start, end)`` UTC-naive 数据库边界。"""
    zone = business_timezone()
    local_start = datetime.combine(target_day, time.min).replace(tzinfo=zone)
    local_end = datetime.combine(target_day + timedelta(days=1), time.min).replace(tzinfo=zone)
    return to_utc_naive(local_start), to_utc_naive(local_end)


def seconds_until_business_day_end(
    target_day: date,
    *,
    now_utc: datetime | None = None,
) -> int:
    """返回距业务日结束的秒数，向上取整以避免账本提前过期。"""
    _, day_end = business_day_utc_bounds(target_day)
    current = to_utc_naive(now_utc or utc_now_naive())
    return math.ceil((day_end - current).total_seconds())
