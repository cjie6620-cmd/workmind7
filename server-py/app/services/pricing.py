"""LLM token 价格与费用计算的唯一后端入口。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..config import config


TOKENS_PER_MILLION = 1_000_000

# 集中默认值仅用于环境变量未配置时；生产环境可按供应商账单价格覆盖。
DEFAULT_INPUT_USD_PER_MILLION = 0.14
DEFAULT_OUTPUT_USD_PER_MILLION = 0.28
DEFAULT_USD_CNY_EXCHANGE_RATE = 7.2
DEFAULT_MAX_OUTPUT_TOKENS = 8_192

INPUT_PRICE_ENV = "LLM_INPUT_PRICE_USD_PER_MILLION"
OUTPUT_PRICE_ENV = "LLM_OUTPUT_PRICE_USD_PER_MILLION"
EXCHANGE_RATE_ENV = "USD_CNY_EXCHANGE_RATE"
MAX_OUTPUT_TOKENS_ENV = "LLM_BUDGET_MAX_OUTPUT_TOKENS"

# 使用 UTF-8 字节数估算输入 token，可避免中英文混排时低估；消息协议开销另行预留。
MESSAGE_OVERHEAD_TOKENS = 16


@dataclass(frozen=True, slots=True)
class PricingConfig:
    """单一模型价格配置，价格单位为每百万 token。"""

    model_name: str
    input_usd_per_million: float
    output_usd_per_million: float
    usd_cny_exchange_rate: float
    max_output_tokens: int
    source: str = "configured"

    @property
    def input_cny_per_million(self) -> float:
        return self.input_usd_per_million * self.usd_cny_exchange_rate

    @property
    def output_cny_per_million(self) -> float:
        return self.output_usd_per_million * self.usd_cny_exchange_rate


@dataclass(frozen=True, slots=True)
class TokenCost:
    """一次模型调用的美元和人民币费用。"""

    usd: float
    cny: float


def _read_positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    value = default if raw_value is None else float(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    value = default if raw_value is None else int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def get_pricing(model_name: str | None = None) -> PricingConfig:
    """读取当前价格配置；不缓存，便于多 worker 以相同环境配置启动。"""
    return PricingConfig(
        model_name=model_name or config["ai"]["primary_model"],
        input_usd_per_million=_read_positive_float(
            INPUT_PRICE_ENV,
            DEFAULT_INPUT_USD_PER_MILLION,
        ),
        output_usd_per_million=_read_positive_float(
            OUTPUT_PRICE_ENV,
            DEFAULT_OUTPUT_USD_PER_MILLION,
        ),
        usd_cny_exchange_rate=_read_positive_float(
            EXCHANGE_RATE_ENV,
            DEFAULT_USD_CNY_EXCHANGE_RATE,
        ),
        max_output_tokens=_read_positive_int(
            MAX_OUTPUT_TOKENS_ENV,
            DEFAULT_MAX_OUTPUT_TOKENS,
        ),
    )


def calculate_token_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    pricing: PricingConfig | None = None,
    model_name: str | None = None,
) -> TokenCost:
    """按统一价格计算 token 费用。"""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must not be negative")

    active_pricing = pricing or get_pricing(model_name)
    cost_usd = (
        input_tokens * active_pricing.input_usd_per_million + output_tokens * active_pricing.output_usd_per_million
    ) / TOKENS_PER_MILLION
    return TokenCost(
        usd=cost_usd,
        cny=cost_usd * active_pricing.usd_cny_exchange_rate,
    )


def estimate_input_tokens(input_value: Any) -> int:
    """
    为预算预留估算输入 token 上限。

    BPE token 数通常不超过 UTF-8 字节数；再为每条消息增加协议开销，避免并发预留低估。
    """
    if input_value is None:
        return MESSAGE_OVERHEAD_TOKENS

    if hasattr(input_value, "to_messages"):
        try:
            input_value = input_value.to_messages()
        except Exception:
            # 无法展开 PromptValue 时仍可使用其字符串表示做保守估算。
            pass

    message_count = len(input_value) if isinstance(input_value, (list, tuple)) else 1
    serialized = repr(input_value)
    byte_count = len(serialized.encode("utf-8"))
    return max(1, byte_count + message_count * MESSAGE_OVERHEAD_TOKENS)


def calculate_reservation_cost(
    input_value: Any,
    *,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> tuple[TokenCost, int, int, PricingConfig]:
    """计算请求前的保守预留费用及其估算依据。"""
    pricing = get_pricing(model_name)
    estimated_input_tokens = estimate_input_tokens(input_value)
    reserved_output_tokens = pricing.max_output_tokens if max_output_tokens is None else max_output_tokens
    if reserved_output_tokens <= 0:
        raise ValueError("max_output_tokens must be greater than 0")

    cost = calculate_token_cost(
        estimated_input_tokens,
        reserved_output_tokens,
        pricing=pricing,
    )
    return cost, estimated_input_tokens, reserved_output_tokens, pricing


def blended_price_cny_per_million(
    pricing: PricingConfig,
    *,
    input_share: float = 0.6,
) -> float:
    """计算监控面板 token 预算换算使用的加权平均单价。"""
    if not 0 <= input_share <= 1:
        raise ValueError("input_share must be between 0 and 1")
    output_share = 1 - input_share
    return pricing.input_cny_per_million * input_share + pricing.output_cny_per_million * output_share
