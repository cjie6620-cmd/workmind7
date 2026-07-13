"""
LLM 调用拦截器模块

通过 MonitoredChatOpenAI 自动拦截所有 LLM 调用，
记录 token 消耗、延迟、异常等指标到监控系统。

零侵入设计：只需在 model.py 中替换 ChatOpenAI → MonitoredChatOpenAI，
所有业务代码无需修改。
"""

import sys
import time

from langchain_openai import ChatOpenAI

from ..routes.monitor import record_api_call


# 调用栈文件路径 → 功能标识映射
_FEATURE_MAP = [
    ('/app/routes/chat.py', 'chat'),
    ('/app/services/chat/', 'chat'),
    ('/app/services/agent/', 'agent'),
    ('/app/services/rag/', 'knowledge'),
    ('/app/services/workflow/', 'workflow'),
    ('/app/services/erp/', 'erp'),
    ('/app/services/prompt/', 'prompt'),
    ('/app/routes/prompt.py', 'prompt'),
]


def _detect_feature() -> str:
    """通过调用栈帧推断当前 LLM 调用的功能模块"""
    frame = sys._getframe()
    while frame:
        filename = frame.f_code.co_filename.replace('\\', '/').lower()
        for path, feature in _FEATURE_MAP:
            if path in filename:
                return feature
        frame = frame.f_back
    return 'chat'


def _extract_tokens(result) -> tuple[int, int]:
    """从 LangChain 结果对象中提取 input/output tokens"""
    usage = getattr(result, 'usage_metadata', None) or {}
    if isinstance(usage, dict):
        return usage.get('input_tokens', 0), usage.get('output_tokens', 0)
    return getattr(usage, 'input_tokens', 0), getattr(usage, 'output_tokens', 0)


class MonitoredChatOpenAI(ChatOpenAI):
    """带自动监控的 ChatOpenAI，拦截 invoke/ainvoke/astream 自动记录指标"""

    def invoke(self, input, config=None, **kwargs):
        start = time.time()
        feature = _detect_feature()
        try:
            result = super().invoke(input, config, **kwargs)
            input_tokens, output_tokens = _extract_tokens(result)
            record_api_call(
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=(time.time() - start) * 1000,
            )
            return result
        except Exception:
            record_api_call(
                feature=feature,
                latency_ms=(time.time() - start) * 1000,
                error=True,
            )
            raise

    async def ainvoke(self, input, config=None, **kwargs):
        from .budget_guard import check_budget_before_llm
        await check_budget_before_llm()
        start = time.time()
        feature = _detect_feature()
        try:
            result = await super().ainvoke(input, config, **kwargs)
            input_tokens, output_tokens = _extract_tokens(result)
            record_api_call(
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=(time.time() - start) * 1000,
            )
            return result
        except Exception:
            record_api_call(
                feature=feature,
                latency_ms=(time.time() - start) * 1000,
                error=True,
            )
            raise

    async def astream(self, input, config=None, **kwargs):
        from .budget_guard import check_budget_before_llm
        await check_budget_before_llm()
        start = time.time()
        feature = _detect_feature()
        chunks = []
        has_error = False

        try:
            async for chunk in super().astream(input, config, **kwargs):
                chunks.append(chunk)
                yield chunk
        except Exception:
            has_error = True
            raise
        finally:
            latency_ms = (time.time() - start) * 1000
            input_tokens, output_tokens = 0, 0
            if chunks:
                input_tokens, output_tokens = _extract_tokens(chunks[-1])
                # 最后一个 chunk 没有 usage 时，尝试合并所有 chunk
                if not input_tokens and not output_tokens and len(chunks) > 1:
                    merged = chunks[0]
                    for c in chunks[1:]:
                        merged = merged + c
                    input_tokens, output_tokens = _extract_tokens(merged)
            record_api_call(
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                error=has_error,
            )
