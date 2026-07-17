"""
LLM 调用拦截器模块

通过 MonitoredChatOpenAI 自动拦截所有 LLM 调用，
记录 token 消耗、延迟、异常等指标到监控系统。

零侵入设计：只需在 model.py 中替换 ChatOpenAI → MonitoredChatOpenAI，
所有业务代码无需修改。
"""

import sys
import time
from types import FrameType
from typing import Any

from langchain_openai import ChatOpenAI

from ..utils.business_time import business_date, utc_now_naive


def _record_api_call(**kwargs):
    """延迟导入监控写入函数，避免 model -> interceptor -> routes 的循环依赖。"""
    try:
        from ..routes.monitor import record_api_call

        record_api_call(**kwargs)
    except Exception as exc:
        # 可观测性故障不得让已经完成的模型调用对用户失败。
        from ..utils.logger import logger

        logger.error(f"[monitor] LLM 调用记录失败: {exc}")


# 调用栈文件路径 → 功能标识映射
_FEATURE_MAP = [
    ("/app/routes/chat.py", "chat"),
    ("/app/services/chat/", "chat"),
    ("/app/services/agent/", "agent"),
    ("/app/services/rag/", "knowledge"),
    ("/app/services/workflow/", "workflow"),
    ("/app/services/erp/", "erp"),
    ("/app/services/prompt/", "prompt"),
    ("/app/routes/prompt.py", "prompt"),
]


def _detect_feature() -> str:
    """通过调用栈帧推断当前 LLM 调用的功能模块"""
    frame: FrameType | None = sys._getframe()
    while frame:
        filename = frame.f_code.co_filename.replace("\\", "/").lower()
        for path, feature in _FEATURE_MAP:
            if path in filename:
                return feature
        frame = frame.f_back
    return "chat"


def _extract_token_usage(result) -> tuple[int, int, bool]:
    """从 LangChain 结果对象中提取 input/output tokens 及 usage 是否存在。"""
    usage = getattr(result, "usage_metadata", None)
    if usage is None:
        return 0, 0, False
    if isinstance(usage, dict):
        usage_known = "input_tokens" in usage or "output_tokens" in usage
        return (
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
            usage_known,
        )
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
        True,
    )


def _model_name(model: ChatOpenAI) -> str | None:
    value = getattr(model, "model_name", None) or getattr(model, "model", None)
    return str(value) if value else None


def _max_output_tokens(model: ChatOpenAI, kwargs: dict[str, Any]) -> int | None:
    """优先使用单次调用上限，否则使用模型实例上限或价格配置上限。"""
    value = kwargs.get("max_output_tokens") or kwargs.get("max_tokens")
    if value is None:
        value = getattr(model, "max_tokens", None)
    return int(value) if value is not None else None


class MonitoredChatOpenAI(ChatOpenAI):
    """带自动监控的 ChatOpenAI，拦截 invoke/ainvoke/astream 自动记录指标"""

    def invoke(self, input, config=None, **kwargs):
        # 同步路径无法可靠接入异步预算守卫；禁止绕过，强制走 ainvoke/astream。
        raise RuntimeError("MonitoredChatOpenAI.invoke 已禁用（会绕过预算守卫），请使用 ainvoke 或 astream")

    async def ainvoke(self, input, config=None, **kwargs):
        from .budget_guard import reserve_budget_before_llm, settle_budget_after_llm

        started_at = utc_now_naive()
        model_name = _model_name(self)
        reservation = await reserve_budget_before_llm(
            input,
            model_name=model_name,
            max_output_tokens=_max_output_tokens(self, kwargs),
            target_day=business_date(started_at),
        )
        start = time.perf_counter()
        feature = _detect_feature()
        try:
            result = await super().ainvoke(input, config, **kwargs)
        except BaseException:
            await settle_budget_after_llm(
                reservation,
                0,
                0,
                usage_known=False,
            )
            _record_api_call(
                feature=feature,
                latency_ms=(time.perf_counter() - start) * 1000,
                error=True,
                model_name=model_name,
                started_at=started_at,
            )
            raise

        input_tokens, output_tokens, usage_known = _extract_token_usage(result)
        await settle_budget_after_llm(
            reservation,
            input_tokens,
            output_tokens,
            usage_known=usage_known,
        )
        _record_api_call(
            feature=feature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=(time.perf_counter() - start) * 1000,
            model_name=model_name,
            started_at=started_at,
        )
        return result

    async def astream(self, input, config=None, **kwargs):
        from .budget_guard import reserve_budget_before_llm, settle_budget_after_llm

        started_at = utc_now_naive()
        model_name = _model_name(self)
        reservation = await reserve_budget_before_llm(
            input,
            model_name=model_name,
            max_output_tokens=_max_output_tokens(self, kwargs),
            target_day=business_date(started_at),
        )
        start = time.perf_counter()
        feature = _detect_feature()
        has_error = False
        input_tokens = 0
        output_tokens = 0
        usage_known = False

        try:
            async for chunk in super().astream(input, config, **kwargs):
                chunk_input, chunk_output, chunk_has_usage = _extract_token_usage(chunk)
                if chunk_has_usage:
                    input_tokens = chunk_input
                    output_tokens = chunk_output
                    usage_known = True
                yield chunk
        except BaseException:
            has_error = True
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            await settle_budget_after_llm(
                reservation,
                input_tokens,
                output_tokens,
                usage_known=usage_known,
            )
            _record_api_call(
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                error=has_error,
                model_name=model_name,
                started_at=started_at,
            )
