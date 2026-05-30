"""
配置管理模块

统一管理所有环境变量，业务代码通过 config 字典访问配置项。
采用延迟加载模式，从 .env 文件读取配置。

配置项：
- app: 端口号、环境模式、CORS 白名单
- ai: DeepSeek API 密钥、模型名称
- chroma: 向量数据库地址
- cache: 缓存 TTL
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# HuggingFace 缓存目录和国内镜像（需在模型加载前设置）
os.environ.setdefault('HF_HOME', _hf_home := os.environ.get('HF_HOME', 'D:/huggingface_cache'))
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')


def _env(key, default=''):
    """读取环境变量，支持默认值"""
    return os.environ.get(key, default)


def _split_env(key, default_list):
    """读取逗号分隔的环境变量列表（如 CORS 白名单）"""
    val = os.environ.get(key, '')
    if val:
        return [s.strip() for s in val.split(',')]
    return default_list


# 配置字典 - 应用层统一配置入口
config = {
    'app': {
        'port': int(_env('PORT', '3001')),
        'env': _env('NODE_ENV', 'development'),
        'allowed_origins': _split_env('ALLOWED_ORIGINS', ['http://localhost:5173']),
    },
    'ai': {
        'deepseek_key': _env('DEEPSEEK_API_KEY'),
        'primary_model': _env('PRIMARY_MODEL', 'deepseek-chat'),
        'base_url': 'https://api.deepseek.com/v1',
        'embedding_model': _env('EMBEDDING_MODEL', 'D:/huggingface_cache/modelscope/Xorbits/bge-m3'),
        'embedding_device': _env('EMBEDDING_DEVICE', 'cpu'),
    },
    'rag': {
        'reranker_model': _env('RERANKER_MODEL', 'BAAI/bge-reranker-v2-m3'),
        'reranker_device': _env('RERANKER_DEVICE', 'cpu'),
        'vector_recall_k': int(_env('VECTOR_RECALL_K', '20')),
        'bm25_recall_k': int(_env('BM25_RECALL_K', '20')),
        'rrf_top_n': int(_env('RRF_TOP_N', '10')),
        'rerank_threshold': float(_env('RERANK_THRESHOLD', '0.2')),
        'final_k': int(_env('FINAL_K', '4')),
    },
    'chroma': {
        'url': _env('CHROMA_URL', 'http://localhost:8000'),
    },
    'mineru': {
        'api_key': _env('MINERU_API_KEY'),
        'timeout': int(_env('MINERU_TIMEOUT', '120')),
        'model_version': _env('MINERU_MODEL_VERSION', 'vlm'),
    },
    'cache': {
        'ttl': int(_env('CACHE_TTL', '1800000')),  # 毫秒，默认 30 分钟
    },
    'redis': {
        'host': _env('REDIS_HOST', 'localhost'),
        'port': int(_env('REDIS_PORT', '6380')),
        'password': _env('REDIS_PASSWORD', 'NFTurbo666'),
        'db': int(_env('REDIS_DB', '0')),
    },
    'database': {
        'url': _env('DATABASE_URL', 'postgresql+asyncpg://ai_love:zx4221335@localhost:5433/ai_love_vector'),
        'pool_size': int(_env('DB_POOL_SIZE', '10')),
        'max_overflow': int(_env('DB_MAX_OVERFLOW', '20')),
    },
}


def validate_config():
    """校验关键配置项，启动时调用"""
    import sys
    if not config['ai']['deepseek_key']:
        print('[ERROR] 缺少 DEEPSEEK_API_KEY, 请在 .env 文件中配置', file=sys.stderr)
        raise SystemExit(1)
    print('[OK] 配置校验通过')