# 结构化日志：开发环境彩色输出，生产环境 JSON 输出
import json
import os
import sys
from datetime import datetime, timezone

is_prod = os.environ.get('NODE_ENV', '') == 'production'

COLORS = {
    'info': '\033[36m',
    'warn': '\033[33m',
    'error': '\033[31m',
    'debug': '\033[90m',
}
RESET = '\033[0m'


def _log(level, msg, ctx=None):
    ctx = ctx or {}
    entry = {
        'time': datetime.now(timezone.utc).isoformat(),
        'level': level,
        'msg': msg,
        **ctx,
    }

    if is_prod:
        sys.stdout.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return

    c = COLORS.get(level, '')
    time_str = entry['time'][11:19]
    ctx_str = ' ' + json.dumps(ctx, ensure_ascii=False) if ctx else ''
    print(f'{c}[{time_str}] {level.upper()} {msg}{ctx_str}{RESET}')


class logger:
    @staticmethod
    def info(msg, ctx=None):
        _log('info', msg, ctx)

    @staticmethod
    def warn(msg, ctx=None):
        _log('warn', msg, ctx)

    @staticmethod
    def error(msg, ctx=None):
        _log('error', msg, ctx)

    @staticmethod
    def debug(msg, ctx=None):
        if not is_prod:
            _log('debug', msg, ctx)
