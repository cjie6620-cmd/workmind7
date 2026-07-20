"""
WorkMind AI Server - Python Edition  →  Mr.Chen AI Server

服务端入口：注册中间件、全局异常处理器与路由。

lifespan 启动序列（生产 strict 模式下任一步失败即退出，禁止带病启动）：
数据库连接与表结构校验 → Redis 连接 → embeddings/reranker 模型预加载（线程池）
→ pgvector 扩展 → 文档注册表 → 监控持久化任务 → 配置/预算/用户种子数据。
关闭序列：等待在途 workflow/erp/agent 任务收尾 → 停监控刷写 → 释放连接池。
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from .config import config, validate_config
from .middleware import setup_middleware
from .utils.errors import AppError
from .utils.logger import logger

from .routes.health import health_router
from .routes.chat import chat_router
from .routes.knowledge import knowledge_router
from .routes.agent import agent_router
from .routes.workflow import workflow_router
from .routes.erp import erp_router
from .routes.prompt import prompt_router
from .routes.monitor import monitor_router
from .services.usage_monitor import start_flush_task, stop_flush_task
from .routes.config import config_router
from .routes.auth import auth_router
from .auth.dependencies import get_current_user, require_admin
from .utils.responses import error_response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期管理：服务启动自检/预加载与关闭时的优雅收尾"""
    validate_config()
    # 生产环境 fail-fast：依赖未就绪宁可拒绝启动，也不提供降级的"半可用"服务
    strict_startup = config["app"]["env"] == "production"
    embedding_required = str(os.environ.get("EMBEDDING_REQUIRED", "true")).lower() in ("1", "true", "yes")

    # 校验数据库连接与迁移状态
    try:
        from .core.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        from .core.database import check_tables_status

        table_status = await check_tables_status()
        if table_status.get("status") != "ready":
            raise RuntimeError(table_status.get("message", "数据库表结构未就绪"))
        print("[OK] 数据库连接成功", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：数据库或迁移未就绪") from e
        print(f"[WARN] 数据库连接失败: {e}", file=sys.stderr)
        print("[WARN] 对话历史、用户画像等功能将不可用", file=sys.stderr)

    # Redis 承担预算、缓存、报告与工作流暂停快照，生产不可降级为假成功。
    try:
        from .core.redis_client import get_redis

        if not await asyncio.to_thread(get_redis().ping):
            raise RuntimeError("Redis ping failed")
        print("[OK] Redis 连接成功", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：Redis 未就绪") from e
        print(f"[WARN] Redis 连接失败: {e}", file=sys.stderr)

    # 预加载 embeddings 模型（线程池，避免阻塞事件循环）
    if config["ai"].get("embedding_model"):
        print("Pre-loading embeddings model...", file=sys.stderr)
        try:
            from .services.model import get_embeddings

            await asyncio.to_thread(get_embeddings)
            print("Embeddings model loaded.", file=sys.stderr)
        except OSError as e:
            if strict_startup and embedding_required:
                raise RuntimeError("生产启动失败：Embeddings 模型无法加载") from e
            print(f"[WARN] Embeddings 模型预加载失败（可能为内存不足/离线缓存缺失）：{e}", file=sys.stderr)
            print("[WARN] 知识库相关功能将不可用或首次请求时才会加载，请确保模型缓存可用", file=sys.stderr)
        except Exception as e:
            if strict_startup and embedding_required:
                raise RuntimeError("生产启动失败：Embeddings 模型无法加载") from e
            print(f"[WARN] Embeddings 模型预加载失败：{e}", file=sys.stderr)

        # 预加载 reranker（同 embeddings），避免首个 RAG 请求同步加载 ~560MB 模型卡死事件循环
        print("Pre-loading reranker model...", file=sys.stderr)
        try:
            from .services.rag.reranker import get_reranker

            await asyncio.to_thread(get_reranker)
            print("Reranker model loaded.", file=sys.stderr)
        except Exception as e:
            if strict_startup and embedding_required:
                raise RuntimeError("生产启动失败：Reranker 模型无法加载") from e
            print(f"[WARN] Reranker 模型预加载失败（首个知识库查询将按需加载）：{e}", file=sys.stderr)
    else:
        print("[WARN] 未配置 EMBEDDING_MODEL，跳过 embeddings 预加载；知识库相关功能将不可用", file=sys.stderr)

    # 确保 pgvector 扩展（表结构由 alembic 管理）
    print("Ensuring pgvector extension...", file=sys.stderr)
    try:
        from .services.rag.pgvector_store import init_pgvector_schema

        await init_pgvector_schema()
        print("pgvector extension ready.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：pgvector 初始化失败") from e
        print(f"[WARN] pgvector 初始化失败: {e}", file=sys.stderr)

    # 加载知识库文档注册表（从数据库恢复，表不存在时不阻塞启动）
    print("Loading document registry...", file=sys.stderr)
    try:
        from .services.rag.ingest import load_doc_registry

        await load_doc_registry()
        print("Document registry loaded.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：文档注册表加载失败") from e
        print(f"[WARN] 文档注册表加载失败: {e}", file=sys.stderr)
        print("[WARN] 知识库相关功能将不可用", file=sys.stderr)

    # 启动用量监控持久化后台任务
    print("Starting monitor flush task...", file=sys.stderr)
    try:
        await start_flush_task()
        print("Monitor flush task started.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：监控持久化任务无法启动") from e
        print(f"[WARN] 监控持久化任务启动失败: {e}", file=sys.stderr)

    # 自动填充配置种子数据（仅首次，表为空时才插入）
    print("Seeding default configs...", file=sys.stderr)
    try:
        from .services.config.config_service import seed_if_empty
        from .services.config.seed_data import PROMPT_SEEDS, AGENT_SEEDS, WORKFLOW_SEEDS

        await seed_if_empty("prompt", PROMPT_SEEDS)
        await seed_if_empty("agent", AGENT_SEEDS)
        await seed_if_empty("workflow", WORKFLOW_SEEDS)
        print("Default configs ready.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：配置种子数据初始化失败") from e
        print(f"[WARN] 配置种子数据初始化失败: {e}", file=sys.stderr)

    # 加载预算配置
    try:
        from .services.usage_monitor import load_budget_from_db

        await load_budget_from_db()
        print("Budget config loaded.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：预算配置加载失败") from e
        print(f"[WARN] 预算配置加载失败: {e}", file=sys.stderr)

    # 种子用户（仅 users 表为空时）
    try:
        from .services.user_seed import ensure_seed_users

        await ensure_seed_users()
        print("Default users ready.", file=sys.stderr)
    except Exception as e:
        if strict_startup:
            raise RuntimeError("生产启动失败：用户数据初始化失败") from e
        print(f"[WARN] 用户种子数据初始化失败: {e}", file=sys.stderr)

    print("\nMr.Chen Server started", file=sys.stderr)
    print(f"   URL: http://localhost:{config['app']['port']}", file=sys.stderr)
    print(f"   Health: http://localhost:{config['app']['port']}/health\n", file=sys.stderr)
    yield
    from .routes.workflow import shutdown_workflow_tasks
    from .routes.erp import shutdown_approval_tasks
    from .routes.agent import shutdown_agent_tasks

    await shutdown_workflow_tasks()
    await shutdown_approval_tasks()
    await shutdown_agent_tasks()
    await stop_flush_task()
    from .core.database import close_db
    from .core.redis_client import close_redis
    from .clients.tavily_client import close_tavily_client

    await close_tavily_client()
    await close_db()
    close_redis()
    logger.info("server shutdown")


_is_production = config["app"]["env"] == "production"

app = FastAPI(
    title="Mr.Chen Server",
    description="Mr.Chen AI 智能办公助手 - Python 版",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# 配置中间件（CORS、限流、请求日志、Prompt 注入检测）
setup_middleware(app)


# ── 全局异常处理器：统一 {"error":{code,message}} 契约，避免纯文本 500 与细节泄露 ──
@app.exception_handler(AppError)
async def _handle_app_error(request: Request, exc: AppError):
    return error_response(exc.status_code, exc.user_message, code=exc.code)


@app.exception_handler(Exception)
async def _handle_unexpected_error(request: Request, exc: Exception):
    # 详细堆栈只进日志；对客户端返回通用文案，不泄露内部细节。
    logger.error("unhandled exception", {"path": request.url.path, "errorType": type(exc).__name__})
    return error_response(500, "服务器内部错误，请稍后重试", code="INTERNAL_ERROR")


# ── 路由注册 ───────────────────────────────────────────────────
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"], dependencies=[Depends(get_current_user)])
app.include_router(
    knowledge_router, prefix="/api/knowledge", tags=["knowledge"], dependencies=[Depends(get_current_user)]
)
app.include_router(agent_router, prefix="/api/agent", tags=["agent"], dependencies=[Depends(get_current_user)])
app.include_router(workflow_router, prefix="/api/workflow", tags=["workflow"], dependencies=[Depends(get_current_user)])
app.include_router(erp_router, prefix="/api/erp", tags=["erp"], dependencies=[Depends(get_current_user)])
app.include_router(prompt_router, prefix="/api/prompt", tags=["prompt"], dependencies=[Depends(require_admin)])
app.include_router(monitor_router, prefix="/api/monitor", tags=["monitor"], dependencies=[Depends(require_admin)])
app.include_router(config_router, prefix="/api/configs", tags=["configs"], dependencies=[Depends(require_admin)])


# 404 处理：未匹配的路由返回友好提示
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(path: str):
    if path.startswith("api/"):
        return error_response(404, f"接口不存在: /{path}")
    return error_response(404, "接口不存在")
