"""
结构化日志模块

提供统一格式的日志输出：
- 开发环境：彩色控制台输出
- 生产环境：JSON 结构化输出

日志级别：
- INFO: 正常信息
- WARN: 警告信息
- ERROR: 错误信息
- DEBUG: 调试信息（仅开发环境）
"""

import json
import os
import sys
from datetime import datetime, timezone

# 是否为生产环境：与 config 一致优先 APP_ENV，兼容旧的 NODE_ENV。
# 生产 Compose 只设 APP_ENV，此前仅判 NODE_ENV 会让生产日志退回彩色/调试输出。
is_prod = (os.environ.get("APP_ENV") or os.environ.get("NODE_ENV", "")) == "production"

# ANSI 颜色码
COLORS = {
    "info": "\033[36m",  # 青色
    "warn": "\033[33m",  # 黄色
    "error": "\033[31m",  # 红色
    "debug": "\033[90m",  # 灰色
}
RESET = "\033[0m"  # 重置颜色


def _log(level, msg, ctx=None):
    """
    统一日志输出

    参数：
    - level: 日志级别
    - msg: 日志消息
    - ctx: 上下文数据（dict）

    开发环境：彩色控制台输出
    - 格式：[时间] LEVEL 消息 {上下文}

    生产环境：JSON 结构化输出
    - 输出到 stdout
    """
    ctx = ctx or {}
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "msg": msg,
        **ctx,
    }

    if is_prod:
        # 生产环境：JSON 输出，便于日志收集和分析
        sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return

    # 开发环境：彩色控制台输出
    c = COLORS.get(level, "")
    time_str = entry["time"][11:19]  # 只取 HH:MM:SS
    ctx_str = " " + json.dumps(ctx, ensure_ascii=False) if ctx else ""
    print(f"{c}[{time_str}] {level.upper()} {msg}{ctx_str}{RESET}")


class logger:
    """
    日志记录器

    提供静态方法，支持不同日志级别：

    - logger.info(msg, ctx=None): 信息日志
    - logger.warn(msg, ctx=None): 警告日志
    - logger.error(msg, ctx=None): 错误日志
    - logger.debug(msg, ctx=None): 调试日志（仅开发环境）
    """

    @staticmethod
    def info(msg, ctx=None):
        """信息日志"""
        _log("info", msg, ctx)

    @staticmethod
    def warn(msg, ctx=None):
        """警告日志"""
        _log("warn", msg, ctx)

    @staticmethod
    def warning(msg, ctx=None):
        """兼容标准 logging 命名，避免告警路径因方法缺失反向失败。"""
        _log("warn", msg, ctx)

    @staticmethod
    def error(msg, ctx=None):
        """错误日志"""
        _log("error", msg, ctx)

    @staticmethod
    def debug(msg, ctx=None):
        """调试日志（生产环境不输出）"""
        if not is_prod:
            _log("debug", msg, ctx)
