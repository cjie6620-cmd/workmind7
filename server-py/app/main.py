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
from .routes.monitor import monitor_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期管理：服务启动和关闭时的清理逻辑"""
    validate_config()

    # 预加载 embeddings 模型，避免在请求处理中首次加载触发 torch 段错误
    import sys
    print('Pre-loading embeddings model...', file=sys.stderr)
    from .services.model import get_embeddings
    get_embeddings()
    print('Embeddings model loaded.', file=sys.stderr)

    print(f'\nWorkMind Server started', file=sys.stderr)
    print(f'   URL: http://localhost:{config["app"]["port"]}', file=sys.stderr)
    print(f'   Health: http://localhost:{config["app"]["port"]}/health\n', file=sys.stderr)
    yield
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


# 404 处理：未匹配的路由返回友好提示
@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def catch_all(path: str):
    return JSONResponse(status_code=404, content={'error': {'message': '接口不存在'}})