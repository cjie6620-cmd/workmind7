# 配置管理：所有环境变量从这里读取，业务代码不直接用 os.environ
import os
from dotenv import load_dotenv

load_dotenv()


def _env(key, default=''):
    return os.environ.get(key, default)


def _split_env(key, default_list):
    val = os.environ.get(key, '')
    if val:
        return [s.strip() for s in val.split(',')]
    return default_list


config = {
    'app': {
        'port': int(_env('PORT', '3000')),
        'env': _env('NODE_ENV', 'development'),
        'allowed_origins': _split_env('ALLOWED_ORIGINS', ['http://localhost:5173']),
    },
    'ai': {
        'deepseek_key': _env('DEEPSEEK_API_KEY'),
        'primary_model': _env('PRIMARY_MODEL', 'deepseek-chat'),
        'base_url': 'https://api.deepseek.com/v1',
    },
    'chroma': {
        'url': _env('CHROMA_URL', 'http://localhost:8000'),
    },
    'cache': {
        'ttl': int(_env('CACHE_TTL', '1800000')),
    },
}


def validate_config():
    import sys
    if not config['ai']['deepseek_key']:
        print('[ERROR] 缺少 DEEPSEEK_API_KEY, 请在 .env 文件中配置', file=sys.stderr)
        raise SystemExit(1)
    print('[OK] 配置校验通过')
