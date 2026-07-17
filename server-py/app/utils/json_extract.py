"""
JSON 提取模块

从 LLM 输出中稳健提取 JSON，处理各种常见噪声：
1. 前后多余文字（如 "以下是结果："、"希望帮到你"）
2. 代码块包裹（```json ... ```）
3. 尾部逗号（,} ,]）
4. 单引号字符串

采用渐进式清洗策略，5 步逐步尝试解析。
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json(text: str):
    """
    从 LLM 输出中提取并解析 JSON

    采用 5 步渐进策略：

    步骤 1: 直接解析
    - 尝试直接 json.loads()

    步骤 2: 代码块提取
    - 提取 ```json ... ``` 或 ``` ... ``` 中的内容

    步骤 3: 花括号截取
    - 找到最外层 { ... } 范围

    步骤 4: 尾逗号清洗
    - 移除 } 或 ] 前的多余逗号，如 ,}

    步骤 5: 单引号替换
    - 将 ' 替换为 "（简单场景有效）

    参数：
    - text: LLM 输出文本

    返回：解析后的 dict/list

    抛出：
    - ValueError: 所有步骤均失败
    """
    text = text.strip()

    # 步骤 1: 直接解析
    try:
        result = json.loads(text)
        logger.debug("JSON 解析成功：步骤1 直接解析")
        return result
    except json.JSONDecodeError:
        logger.debug("步骤1 直接解析失败，尝试步骤2 提取代码块")

    # 步骤 2: 提取代码块
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        inner = code_block.group(1).strip()
        try:
            result = json.loads(inner)
            logger.debug("JSON 解析成功：步骤2 代码块提取")
            return result
        except json.JSONDecodeError:
            logger.debug("步骤2 代码块解析失败，继续后续清洗")
            text = inner

    # 步骤 3: 提取最外层 { ... }
    json_start = None
    idx = text.find("{")
    if idx != -1:
        ridx = text.rfind("}")
        if ridx > idx:
            candidate = text[idx : ridx + 1]
            try:
                result = json.loads(candidate)
                logger.debug("JSON 解析成功：步骤3 花括号截取")
                return result
            except json.JSONDecodeError:
                logger.debug("步骤3 花括号截取解析失败，尝试步骤4 清洗尾逗号")
                json_start = candidate

    # 步骤 4: 清洗尾部逗号
    if json_start:
        cleaned = re.sub(r",\s*}", "}", json_start)
        try:
            result = json.loads(cleaned)
            logger.debug("JSON 解析成功：步骤4 清洗尾逗号")
            return result
        except json.JSONDecodeError:
            logger.debug("步骤4 清洗尾逗号失败，尝试步骤5 单引号替换")

    # 步骤 5: 单引号替换
    if json_start:
        replaced = json_start.replace("'", '"')
        try:
            result = json.loads(replaced)
            logger.debug("JSON 解析成功：步骤5 单引号替换")
            return result
        except json.JSONDecodeError:
            logger.debug("步骤5 单引号替换失败，所有步骤均无法解析")

    raise ValueError(f"无法从输出中提取有效 JSON: {text[:200]}")
