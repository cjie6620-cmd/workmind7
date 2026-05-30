"""
WorkMind AI Server - Python Edition

服务端入口：注册中间件、路由，启动 FastAPI 服务。
采用 lifespan 上下文管理器处理启动和关闭逻辑。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from .config import config, validate_config
from .middleware import setup_middleware
from .utils.logger import logger

from .routes.health import health_router
from .routes.chat import chat_router
from .routes.knowledge import knowledge_router
from .routes.agent import agent_router
from .routes.workflow import workflow_router
from .routes.erp import erp_router
from .routes.prompt import prompt_router
from .routes.monitor import monitor_router, start_flush_task, stop_flush_task
from .routes.config import config_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期管理：服务启动和关闭时的清理逻辑"""
    validate_config()

    # 校验数据库连接
    import sys
    try:
        from .core.database import async_session_factory
        from sqlalchemy import text
        async with async_session_factory() as session:
            await session.execute(text('SELECT 1'))
        print('[OK] 数据库连接成功', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] 数据库连接失败: {e}', file=sys.stderr)
        print('[WARN] 对话历史、用户画像等功能将不可用', file=sys.stderr)

    # 预加载 embeddings 模型（失败不阻塞启动，后续请求时按需加载）
    print('Pre-loading embeddings model...', file=sys.stderr)
    try:
        from .services.model import get_embeddings
        get_embeddings()
        print('Embeddings model loaded.', file=sys.stderr)
    except OSError as e:
        print(f'[WARN] Embeddings 模型预加载失败（内存不足）：{e}', file=sys.stderr)
        print('[WARN] 知识库相关功能将在首次请求时加载，请确保系统内存充足', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] Embeddings 模型预加载失败：{e}', file=sys.stderr)

    # 初始化 pgvector 扩展和表结构（含已有数据库的列类型迁移）
    print('Initializing pgvector schema...', file=sys.stderr)
    try:
        from .services.rag.pgvector_store import init_pgvector_schema
        await init_pgvector_schema()
        print('pgvector schema ready.', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] pgvector 初始化失败: {e}', file=sys.stderr)

    # 加载知识库文档注册表（从数据库恢复，表不存在时不阻塞启动）
    print('Loading document registry...', file=sys.stderr)
    try:
        from .services.rag.ingest import load_doc_registry
        await load_doc_registry()
        print('Document registry loaded.', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] 文档注册表加载失败: {e}', file=sys.stderr)
        print('[WARN] 知识库相关功能将不可用', file=sys.stderr)

    # 启动用量监控持久化后台任务
    print('Starting monitor flush task...', file=sys.stderr)
    try:
        await start_flush_task()
        print('Monitor flush task started.', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] 监控持久化任务启动失败: {e}', file=sys.stderr)

    # 自动填充配置种子数据（仅首次，表为空时才插入）
    print('Seeding default configs...', file=sys.stderr)
    try:
        from .services.config.config_service import seed_if_empty
        from .services.config.seed_data import PROMPT_SEEDS, AGENT_SEEDS, WORKFLOW_SEEDS
        await seed_if_empty('prompt', PROMPT_SEEDS)
        await seed_if_empty('agent', AGENT_SEEDS)
        await seed_if_empty('workflow', WORKFLOW_SEEDS)
        print('Default configs ready.', file=sys.stderr)
    except Exception as e:
        print(f'[WARN] 配置种子数据初始化失败: {e}', file=sys.stderr)

    print(f'\nWorkMind Server started', file=sys.stderr)
    print(f'   URL: http://localhost:{config["app"]["port"]}', file=sys.stderr)
    print(f'   Health: http://localhost:{config["app"]["port"]}/health\n', file=sys.stderr)
    yield
    await stop_flush_task()
    logger.info('server shutdown')


app = FastAPI(
    title='WorkMind Server',
    description='WorkMind AI 智能办公助手 - Python 版',
    version='1.0.0',
    lifespan=lifespan,
)

# 配置中间件（CORS、限流、请求日志、Prompt 注入检测）
setup_middleware(app)

# ── 路由注册 ───────────────────────────────────────────────────
app.include_router(health_router, prefix='/health', tags=['health'])
app.include_router(chat_router, prefix='/api/chat', tags=['chat'])
app.include_router(knowledge_router, prefix='/api/knowledge', tags=['knowledge'])
app.include_router(agent_router, prefix='/api/agent', tags=['agent'])
app.include_router(workflow_router, prefix='/api/workflow', tags=['workflow'])
app.include_router(erp_router, prefix='/api/erp', tags=['erp'])
app.include_router(prompt_router, prefix='/api/prompt', tags=['prompt'])
app.include_router(monitor_router, prefix='/api/monitor', tags=['monitor'])
app.include_router(config_router, prefix='/api/configs', tags=['configs'])


# 404 处理：未匹配的路由返回友好提示
@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def catch_all(path: str):
    # /api 路径不应走到这里，说明路由注册有问题，返回 500 方便排查
    if path.startswith('api/'):
        return JSONResponse(status_code=500, content={'error': {'message': f'路由未匹配: /{path}'}})
    return JSONResponse(status_code=404, content={'error': {'message': '接口不存在'}})
