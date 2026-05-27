"""
Utils 工具层模块

提供通用工具函数：
- errors: 错误分类和 SSE 错误格式化
- json_extract: 从 LLM 输出中提取 JSON
- logger: 结构化日志（彩色/JSON）
"""

from .logger import logger

__all__ = ['logger']