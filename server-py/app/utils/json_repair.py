"""
JSON 修复模块

从 LLM 输出中稳健提取并修复 JSON，8 步渐进式策略：
1. 直接解析
2. 代码块提取
3. 花括号截取
4. 尾逗号清洗
5. 单引号替换
6. 截断修复（补全缺失的 } ]）
7. 注释移除（// 和 /* */）
8. 转义修复（\n \t \r 未正确转义）
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class JsonRepair:
    """JSON 修复工具类，从破损 LLM 输出中提取有效 JSON"""

    @classmethod
    def repair(cls, text: str) -> Any:
        """
        主入口：从 LLM 输出中提取并修复 JSON

        返回解析后的 dict/list，所有策略均失败时抛出 ValueError。
        """
        text = text.strip()
        if not text:
            raise ValueError('输入为空，无法提取 JSON')

        for step_name, step_fn in cls._steps():
            try:
                result = step_fn(text)
                if result is not None:
                    logger.debug(f'JSON 修复成功：{step_name}')
                    return result
            except Exception:
                continue

        raise ValueError(f'无法从输出中提取有效 JSON: {text[:200]}')

    @classmethod
    def _steps(cls):
        """修复步骤列表，按优先级排列"""
        return [
            ('直接解析', cls._try_direct),
            ('代码块提取', cls._try_code_block),
            ('花括号截取', cls._try_brace_extract),
            ('尾逗号清洗', cls._try_trailing_comma),
            ('单引号替换', cls._try_single_quotes),
            ('截断修复', cls._try_truncate_fix),
            ('注释移除', cls._try_remove_comments),
            ('转义修复', cls._try_escape_fix),
        ]

    @staticmethod
    def _try_direct(text):
        return json.loads(text)

    @staticmethod
    def _try_code_block(text):
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if match:
            inner = match.group(1).strip()
            result = json.loads(inner)
            return result
        return None

    @staticmethod
    def _try_brace_extract(text):
        idx = text.find('{')
        ridx = text.rfind('}')
        if idx != -1 and ridx > idx:
            return json.loads(text[idx:ridx + 1])
        return None

    @staticmethod
    def _try_trailing_comma(text):
        idx = text.find('{')
        ridx = text.rfind('}')
        if idx == -1 or ridx <= idx:
            return None
        candidate = text[idx:ridx + 1]
        cleaned = re.sub(r',(\s*[}\]])', r'\1', candidate)
        return json.loads(cleaned)

    @staticmethod
    def _try_single_quotes(text):
        idx = text.find('{')
        ridx = text.rfind('}')
        if idx == -1 or ridx <= idx:
            return None
        candidate = text[idx:ridx + 1].replace("'", '"')
        return json.loads(candidate)

    @staticmethod
    def _try_truncate_fix(text):
        """补全缺失的 } ]，修复被截断的 JSON"""
        idx = text.find('{')
        if idx == -1:
            return None
        candidate = text[idx:]
        open_curly = candidate.count('{') - candidate.count('}')
        open_square = candidate.count('[') - candidate.count(']')
        # 去掉末尾不完整的 key/value
        candidate = re.sub(r'[,"][^"]*$', '', candidate)
        candidate += ']' * max(open_square, 0) + '}' * max(open_curly, 0)
        return json.loads(candidate)

    @staticmethod
    def _try_remove_comments(text):
        """移除 // 和 /* */ 注释"""
        idx = text.find('{')
        if idx == -1:
            return None
        candidate = text[idx:]
        candidate = re.sub(r'//.*', '', candidate)
        candidate = re.sub(r'/\*.*?\*/', '', candidate, flags=re.DOTALL)
        return json.loads(candidate)

    @staticmethod
    def _try_escape_fix(text):
        """修复未正确转义的控制字符"""
        idx = text.find('{')
        if idx == -1:
            return None
        candidate = text[idx:]
        # 仅在字符串值内部修复（简单启发式）
        candidate = re.sub(r'(?<!\\)\\n', '\\\\n', candidate)
        candidate = re.sub(r'(?<!\\)\\t', '\\\\t', candidate)
        candidate = re.sub(r'(?<!\\)\\r', '\\\\r', candidate)
        return json.loads(candidate)
