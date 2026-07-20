"""
配置管理模块

统一管理所有环境变量：import 时执行 load_dotenv() 读入 .env（不覆盖已存在的
环境变量，因此测试 conftest 先行注入的值优先生效），业务代码通过 config 字典访问。

配置分组：
- app: 端口、环境模式（APP_ENV 优先，兼容旧 NODE_ENV）、CORS 白名单、业务时区
- ai: DeepSeek API 密钥、主力模型、embedding 模型与调用护栏（max_tokens/超时/重试）
- rag: reranker 模型与混合检索召回/精排参数
- mineru / tavily: 第三方解析与联网搜索凭据
- cache / redis / database: 缓存 TTL、Redis 连接、PostgreSQL 连接池
- auth: JWT 开关、密钥与过期策略
- budget: 日预算与强制模式

启动时必须调用 validate_config() 做 fail-fast 校验（见 main.py lifespan）。
"""

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# HuggingFace 缓存目录和国内镜像（需在模型加载前设置）
_hf_home = os.environ.get("HF_HOME", "")
if _hf_home:
    os.environ.setdefault("HF_HOME", _hf_home)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _env(key, default=""):
    """读取环境变量，支持默认值"""
    return os.environ.get(key, default)


def _split_env(key, default_list):
    """读取逗号分隔的环境变量列表（如 CORS 白名单）"""
    val = os.environ.get(key, "")
    if val:
        return [s.strip() for s in val.split(",")]
    return default_list


# 配置字典 - 应用层统一配置入口
config = {
    "app": {
        "port": int(_env("PORT", "3001")),
        "env": _env("APP_ENV") or _env("NODE_ENV", "development"),
        "allowed_origins": _split_env("ALLOWED_ORIGINS", ["http://localhost:5173"]),
        "business_timezone": _env("BUSINESS_TIMEZONE", "Asia/Shanghai"),
    },
    "ai": {
        "deepseek_key": _env("DEEPSEEK_API_KEY"),
        "primary_model": _env("PRIMARY_MODEL", "deepseek-chat"),
        "base_url": "https://api.deepseek.com/v1",
        "embedding_model": _env("EMBEDDING_MODEL"),
        "embedding_device": _env("EMBEDDING_DEVICE", "cpu"),
        "max_tokens": int(_env("LLM_MAX_TOKENS", "4096")),
        "timeout_seconds": float(_env("LLM_TIMEOUT_SECONDS", "60")),
        "max_retries": int(_env("LLM_MAX_RETRIES", "2")),
    },
    "rag": {
        "reranker_model": _env("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        "reranker_device": _env("RERANKER_DEVICE", "cpu"),
        "vector_recall_k": int(_env("VECTOR_RECALL_K", "20")),
        "bm25_recall_k": int(_env("BM25_RECALL_K", "20")),
        "rerank_threshold": float(_env("RERANK_THRESHOLD", "0.2")),
        "final_k": int(_env("FINAL_K", "4")),
    },
    "mineru": {
        "api_key": _env("MINERU_API_KEY"),
        "timeout": int(_env("MINERU_TIMEOUT", "120")),
        "model_version": _env("MINERU_MODEL_VERSION", "vlm"),
    },
    "tavily": {
        "api_key": _env("TAVILY_API_KEY"),
        "timeout": int(_env("TAVILY_TIMEOUT", "30")),
        "max_results": int(_env("TAVILY_MAX_RESULTS", "5")),
    },
    "cache": {
        "ttl": int(_env("CACHE_TTL", "1800000")),  # 毫秒，默认 30 分钟
    },
    "redis": {
        "host": _env("REDIS_HOST", "localhost"),
        "port": int(_env("REDIS_PORT", "6381")),
        "password": _env("REDIS_PASSWORD"),
        "db": int(_env("REDIS_DB", "0")),
    },
    "database": {
        "url": _env("DATABASE_URL"),
        "pool_size": int(_env("DB_POOL_SIZE", "10")),
        "max_overflow": int(_env("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": int(_env("DB_POOL_RECYCLE", "1800")),
        "pool_timeout": int(_env("DB_POOL_TIMEOUT", "30")),
    },
    "auth": {
        "enabled": _env("AUTH_ENABLED", "true").lower() in ("1", "true", "yes"),
        "jwt_secret": _env("JWT_SECRET"),
        "jwt_expire_hours": int(_env("JWT_EXPIRE_HOURS", "24")),
        "jwt_refresh_expire_days": int(_env("JWT_REFRESH_EXPIRE_DAYS", "7")),
        "jwt_algorithm": _env("JWT_ALGORITHM", "HS256"),
    },
    "budget": {
        "enforce": _env("BUDGET_ENFORCE", "false").lower() in ("1", "true", "yes"),
        "daily_budget": float(_env("DAILY_BUDGET", "50")),
    },
}


def validate_config():
    """校验关键配置项，启动时调用"""
    import sys

    if not config["ai"]["deepseek_key"]:
        print("[ERROR] 缺少 DEEPSEEK_API_KEY, 请在 .env 文件中配置", file=sys.stderr)
        raise SystemExit(1)

    if not config["database"]["url"]:
        print("[ERROR] 缺少 DATABASE_URL, 请在 .env 文件中配置", file=sys.stderr)
        raise SystemExit(1)

    try:
        ZoneInfo(config["app"]["business_timezone"])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        print(
            "[ERROR] BUSINESS_TIMEZONE 必须是有效的 IANA 时区（如 Asia/Shanghai）",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not 1 <= config["ai"]["max_tokens"] <= 32_000:
        print("[ERROR] LLM_MAX_TOKENS 必须在 1 到 32000 之间", file=sys.stderr)
        raise SystemExit(1)
    if not 1 <= config["ai"]["timeout_seconds"] <= 300:
        print("[ERROR] LLM_TIMEOUT_SECONDS 必须在 1 到 300 秒之间", file=sys.stderr)
        raise SystemExit(1)
    if not 0 <= config["ai"]["max_retries"] <= 5:
        print("[ERROR] LLM_MAX_RETRIES 必须在 0 到 5 之间", file=sys.stderr)
        raise SystemExit(1)

    if config["app"]["env"] == "production" and not config["redis"]["password"]:
        print("[ERROR] 生产环境必须设置 REDIS_PASSWORD", file=sys.stderr)
        raise SystemExit(1)

    if config["app"]["env"] == "production":
        origins = config["app"]["allowed_origins"]
        if "*" in origins:
            print("[ERROR] 生产环境 ALLOWED_ORIGINS 禁止包含 *", file=sys.stderr)
            raise SystemExit(1)

        # 生产必须启用认证：AUTH_ENABLED=false 会让所有请求走 dev 免认证后门并获得 admin 权限。
        if not config["auth"]["enabled"]:
            print("[ERROR] 生产环境禁止 AUTH_ENABLED=false（会启用免认证 admin 后门）", file=sys.stderr)
            raise SystemExit(1)

    if not config["redis"]["password"] and config["app"]["env"] != "production":
        print("[WARN] REDIS_PASSWORD 未设置，开发环境 Redis 无密码", file=sys.stderr)

    if config["auth"]["enabled"]:
        secret = config["auth"]["jwt_secret"]
        if not secret or len(secret) < 32:
            print("[ERROR] AUTH_ENABLED=true 时 JWT_SECRET 必填且长度 ≥ 32 字符", file=sys.stderr)
            raise SystemExit(1)

    print("[OK] 配置校验通过")
