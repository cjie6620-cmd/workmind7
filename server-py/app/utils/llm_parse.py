"""
LLM 结构化输出解析工具

提供 parse_with_retry：
LLM 调用 → JsonRepair 修复 → Pydantic 校验 → 失败自动重试（将错误反馈给 LLM 自我修正）

所有需要 LLM 返回结构化 JSON 的场景统一使用此工具。
"""

from pydantic import ValidationError

from .json_repair import JsonRepair
from .logger import logger


def _format_validation_error(err: ValidationError) -> str:
    """将 Pydantic ValidationError 格式化为简洁描述，用于反馈给 LLM"""
    lines = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e["loc"])
        lines.append(f"- {loc}: {e['msg']}")
    return "\n".join(lines)


async def parse_with_retry(model, messages, model_cls, max_retries=2):
    """
    带重试的结构化解析

    流程：LLM 调用 → JsonRepair 提取 → Pydantic 校验
    失败时将错误反馈给 LLM 自我修正，最多重试 max_retries 次

    参数:
    - model: LangChain ChatModel 实例
    - messages: 消息列表（会被浅拷贝，不污染调用方）
    - model_cls: Pydantic 模型类
    - max_retries: 最大重试次数（不含首次调用）
    """
    messages = list(messages)

    for attempt in range(max_retries + 1):
        resp = await model.ainvoke(messages)
        raw = resp.content

        try:
            data = JsonRepair.repair(raw)
        except ValueError as e:
            if attempt < max_retries:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"JSON 提取失败：{e}。请重新输出完整的有效 JSON。"})
                logger.warning(f"llm_parse: json repair failed, retry {attempt + 1}")
                continue
            raise

        try:
            return model_cls.model_validate(data)
        except ValidationError as e:
            if attempt < max_retries:
                error_detail = _format_validation_error(e)
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"JSON 结构验证失败：\n{error_detail}\n请修正后重新输出。"})
                logger.warning(f"llm_parse: pydantic validation failed, retry {attempt + 1}")
                continue
            raise
