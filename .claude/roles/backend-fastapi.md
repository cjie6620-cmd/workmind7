# Backend-FastAPI 规范（异步栈）

> 适用场景：Python 3.12+ / FastAPI 0.136+ / SQLAlchemy 2.0 async / LLM 应用后端开发。
>
> 与 [agent.md](agent.md)（RAG/Agent/LLM Ops）/ [dba.md](dba.md)（数据库）/ [devops.md](devops.md)（部署）/ [frontend.md](frontend.md)（前端 API 协议）/ [reviewer.md](reviewer.md)（代码审查）协同。
>
> 如果你使用的是 Flask 同步框架，参见 [backend-flask.md](backend-flask.md)。

---

## 技术栈（必须遵守）

| 组件 | 版本 | 说明 | 不用 |
|------|------|------|------|
| **Python** | 3.12+ | 结构化匹配、type 语法、asyncio 改进 | ❌ 3.11 及以下 |
| **包管理** | uv 0.4+ | 替代 pip + venv + pip-tools | ❌ pip / poetry / pdm |
| **Web 框架** | FastAPI 0.136.3+ | 异步、原生 OpenAPI、依赖注入（官方 `__init__.py` 确认） | ❌ Flask / Django（同步） |
| **ASGI 服务器（开发）** | uvicorn[standard] 0.32+ | 热重载 | — |
| **ASGI 服务器（生产）** | gunicorn 23+ + uvicorn workers | 多进程 + 异步 worker | ❌ 裸 uvicorn |
| **数据校验** | Pydantic v2.10+ | Rust 核心、5-50x 性能（`model_config = ConfigDict(...)`） | ❌ Pydantic v1（已 EOL） |
| **ORM** | SQLAlchemy 2.0.36+ (async) | 类型安全 `Mapped[T]` 风格，`create_async_engine` | ❌ SQLAlchemy 1.x / Tortoise ORM |
| **迁移** | Alembic 1.14+ | SQLAlchemy 官方迁移 | ❌ 手动 SQL 改库 |
| **HTTP 客户端** | httpx 0.27+ | async/sync 双模 | ❌ requests（同步） |
| **日志** | loguru 0.7+ | 结构化、自动轮转 | ❌ stdlib logging（配置繁琐） |
| **配置** | pydantic-settings 2.6+ | 类型安全 .env | ❌ python-dotenv 裸用 |
| **测试** | pytest 8+ + pytest-asyncio 0.24+ + httpx | AsyncClient | ❌ unittest |
| **Mock** | factory-boy + faker | 测试数据生成 | ❌ 硬编码测试数据 |
| **任务队列（轻量）** | arq 0.25+ | 异步、Redis 后端 | — |
| **任务队列（重）** | Celery 5.4+ | 复杂任务编排 | — |
| **依赖注入** | FastAPI Depends | 框架原生 | ❌ pinject / dependency-injector |
| **限流** | slowapi 0.1.9+ | FastAPI 集成 | — |
| **JWT** | pyjwt 2.9+ | 简单场景 | ❌ jose（仅 OAuth2） |
| **API 文档** | FastAPI 原生 OpenAPI | /docs (Swagger UI) | — |

### 版本来源说明

以上版本均通过 **Context7 查询官方文档** 确认（2026-06）：
- FastAPI 0.136.3 → `fastapi/fastapi` 官方 `__init__.py` 中 `__version__`
- Pydantic v2.10+ → `pydantic/pydantic` 官方，`model_config = ConfigDict(...)` 替代内嵌 `Config` 类
- SQLAlchemy 2.0.36+ → `sqlalchemy_en_20` 官方文档
- Alembic 1.14+ → SQLAlchemy 官方配套

---

## 技术选型理由（半成品项目视角）

> 假设你已启动一个 FastAPI LLM 应用项目（有代码骨架，业务逻辑逐步填充），以下解释每个技术组件在项目中**解决什么问题**。

### 核心框架层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **FastAPI 0.136** | 异步 Web 框架，处理 HTTP 请求 | 原生 async/await，性能接近 Go/Node；自动 OpenAPI 文档；`Depends` 依赖注入零样板代码 |
| **uvicorn + gunicorn** | ASGI 服务器（并发处理请求） | uvicorn 异步事件循环（开发），gunicorn 多进程 + uvicorn worker（生产）|
| **APIRouter** | 路由模块化（按业务域拆分） | 支持嵌套 `include_router()`，前缀/标签自动继承，适合多模块项目 |

### 数据校验层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **Pydantic v2** | 请求体/响应体校验 + 序列化 | Rust 核心性能碾压 v1；`model_config = ConfigDict(from_attributes=True)` 直接从 ORM 转换 |
| **pydantic-settings** | 配置文件管理（.env → 类型安全） | 替代 python-dotenv 裸用，配置项有类型校验、必填校验、默认值 |

> **Pydantic v2 关键变化**：`Config` 内嵌类已废弃，必须用 `model_config = ConfigDict(...)`。半成品项目如果看到旧写法（`class Config: ...`），应立即迁移。

### 数据层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **SQLAlchemy 2.0 async** | ORM + 数据库连接池 | `create_async_engine` + `async_sessionmaker`，请求级别 Session 自动管理 |
| **asyncpg / aiomysql** | 异步数据库驱动 | asyncpg（PostgreSQL）性能最优；aiomysql（MySQL）兼容性好 |
| **Alembic** | 数据库迁移（版本化表结构变更） | SQLAlchemy 官方配套，`alembic revision --autogenerate` 自动检测模型变化 |

### 架构层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **Depends 注入** | 跨层调用解耦（API → Service → Repository） | FastAPI 原生，替代 `dependency-injector` 等第三方库 |
| **Repository 模式** | 封装数据访问（可选） | 复杂查询（join/aggregate）集中在一处，Service 层不感知 SQL |

> **Depends 注入原理**（官方推荐写法）：
> ```python
> # 用 Annotated 声明依赖，FastAPI 自动注入
> async def read_items(commons: Annotated[dict, Depends(common_parameters)]):
>     return commons
> ```
> - `Depends(fn)` 声明「这个路由需要 fn 的返回值」
> - FastAPI 自动调用 fn，把结果注入到 `commons` 参数
> - 链式依赖：`get_db_session → get_user_repo → get_auth_service`，每层只关心自己的依赖
> - **限制**：链不超过 4 层（超过说明需要重构）

### 可观测与安全

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **loguru** | 日志 | 开箱即用，比标准 logging 配置简单 10 倍 |
| **slowapi** | 接口限流 | FastAPI 原生集成，`@limiter.limit("5/minute")` 即可 |
| **pyjwt** | JWT 认证 | 轻量，无外部依赖（不像 jose 有 OAuth2 背景） |

---

## 避坑清单（FastAPI 异步陷阱）

按严重程度排序：

### 🔴 致命

1. **禁止在 `async def` 路由中调用同步阻塞 IO**（如 `requests.get` / `time.sleep` / 文件 IO） → 阻塞 event loop，整个服务卡死
2. **禁止 LLM 调用无 `max_tokens` / `timeout`** → 详见 [agent.md §二](agent.md#二避坑清单llm-专属20-条)
3. **禁止 ORM 同步 session 与 async session 混用** → 跨线程问题
4. **禁止 Depends 中返回可变全局状态** → 多个请求共享导致竞态
5. **禁止数据库连接池配置过小**（生产 < 20） → 性能瓶颈
6. **禁止 LLM API Key 写死在代码或提交到 git** → 必须走 .env / Secret Manager
7. **禁止调用任何国外 LLM API（OpenAI / Anthropic / Cohere / Jina）** → 全部使用国产模型（DeepSeek / 通义 / GLM），**违反视为重大事故**

### 🟠 严重

7. **禁止 `sync def` 路由中做 IO 密集操作** → FastAPI 会用 thread pool 跑，但阻塞会拖慢线程池
8. **禁止数据库事务跨多个 HTTP 请求** → 必须单请求单事务
9. **禁止无 background task 时长限制** → 后台任务卡死
10. **禁止 Pydantic model 不声明 `model_config`** → v2 行为变化
11. **禁止不用 lifespan 管理资源**（连接池、模型加载） → 已弃用 `@app.on_event("startup")`

### 🟡 重要

12. **禁止不用 type hints** → FastAPI 失去自动文档生成能力
13. **禁止 Pydantic 默认值用可变对象**（如 `field: list = []`） → 共享同一对象
14. **禁止异常处理吞掉原始异常**（`except: pass`） → 排查地狱
15. **禁止 SQLAlchemy 懒加载跨 session 访问** → `MissingGreenlet` 错误

---

## 开发命令

```bash
# 项目初始化（必须用 uv，不用 pip / poetry）
uv init my-project
cd my-project
uv add fastapi 'uvicorn[standard]' sqlalchemy[asyncio] asyncpg alembic pydantic pydantic-settings loguru httpx

# 开发环境
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产环境（多 worker）
uv run gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# 数据库迁移
uv run alembic revision --autogenerate -m "add user table"
uv run alembic upgrade head
uv run alembic downgrade -1

# 测试
uv run pytest                              # 全部
uv run pytest tests/test_user.py          # 单文件
uv run pytest -k "test_login"              # 关键字
uv run pytest --cov=app --cov-report=html # 覆盖率

# 代码质量
uv run ruff check .
uv run ruff format .
uv run mypy app/
```

---

## 项目结构

```
my-project/
├── app/
│   ├── main.py                  # FastAPI app 入口
│   ├── core/                    # 全局配置
│   │   ├── config.py            # Pydantic Settings
│   │   ├── logging.py           # loguru 配置
│   │   ├── security.py          # JWT / 密码哈希
│   │   └── lifespan.py          # 资源生命周期
│   ├── api/                     # 路由层（Controller）
│   │   ├── deps.py              # 公共 Depends
│   │   └── v1/
│   │       ├── chat.py          # /api/v1/chat
│   │       ├── documents.py
│   │       └── users.py
│   ├── schemas/                 # Pydantic Schema（DTO/VO）
│   │   ├── chat.py
│   │   └── common.py            # 统一响应体 R[T]
│   ├── models/                  # SQLAlchemy ORM（详见 dba.md）
│   ├── services/                # 业务逻辑层
│   │   ├── chat_service.py
│   │   └── document_service.py
│   ├── repositories/            # 数据访问层（可选）
│   ├── llm/                     # LLM 相关（详见 agent.md）
│   │   ├── clients.py
│   │   └── prompts/
│   ├── rag/                     # RAG 相关（详见 agent.md）
│   ├── agents/                  # Agent 相关（详见 agent.md）
│   ├── middleware/              # 中间件
│   └── exceptions.py            # 自定义异常
├── alembic/                     # 数据库迁移
├── tests/
│   ├── conftest.py
│   ├── test_*.py
│   └── eval/                    # 离线评估
├── pyproject.toml
├── alembic.ini
├── .env.example
└── README.md
```

---

## lifespan 资源生命周期（FastAPI 官方推荐）

> `@app.on_event("startup")` 已废弃（FastAPI 0.103+），必须用 `lifespan` 管理资源。

```python
# app/core/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings

# 全局资源
engine = None
ml_models = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    # ---- 启动时 ----
    engine = create_async_engine(settings.DATABASE_URL, pool_size=20)
    # 可加载 ML 模型、初始化 Redis 连接池等
    ml_models["embedding"] = load_embedding_model()
    yield
    # ---- 关闭时 ----
    await engine.dispose()
    ml_models.clear()

# main.py
app = FastAPI(lifespan=lifespan)
```

**为什么要用 lifespan**：
- 连接池、模型加载等重资源在启动时初始化一次（不用每个请求都创建）
- 关闭时 `await engine.dispose()` 优雅释放连接，避免连接泄露
- 测试时可以用 `app.dependency_overrides` 替换，lifespan 不影响单元测试

---

## 分层规范（API → Service → Repository）

**强制四层架构**，每层职责严格分离：

```
HTTP Request
    ↓
┌──────────────────────────────────────┐
│ API Layer（app/api/v1/）            │ ← 接收请求、参数校验、调用 Service、返回响应
│ - FastAPI 路由                        │   不写业务逻辑！
│ - Pydantic Schema 校验                │
│ - Depends 注入 Service                │
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ Service Layer（app/services/）      │ ← 业务逻辑、流程编排、事务控制
│ - 纯函数 / 类                         │   不直接操作 ORM！
│ - 可被多个 API 复用                   │   通过 Repository 访问数据
│ - 异常抛出由 API 层捕获               │
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ Repository Layer（app/repositories/）│ ← 数据访问封装
│ - 封装 SQLAlchemy 查询                │   业务层不感知 SQL
│ - 复杂查询（join / aggregate）         │
│ - 可选：小型项目可省略                 │
└──────────────────────────────────────┘
    ↓
┌──────────────────────────────────────┐
│ Model Layer（app/models/）          │ ← SQLAlchemy ORM（详见 dba.md）
└──────────────────────────────────────┘
```

### 示例：用户登录全链路

```python
# === 第一步：Schema（schemas/user.py）===
from pydantic import BaseModel, EmailStr, Field

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int


# === 第二步：Repository（repositories/user_repo.py）===
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


# === 第三步：Service（services/auth_service.py）===
from app.core.security import verify_password, create_access_token
from app.repositories.user_repo import UserRepository
from app.exceptions import UnauthorizedException

class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def login(self, email: str, password: str) -> tuple[str, int]:
        user = await self.user_repo.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise UnauthorizedException("Invalid credentials")

        token = create_access_token({"sub": str(user.id)})
        return token, user.id


# === 第四步：API（api/v1/auth.py）===
from fastapi import APIRouter, Depends
from app.api.deps import get_db_session, get_auth_service
from app.schemas.user import LoginRequest, LoginResponse
from app.services.auth_service import AuthService
from app.schemas.common import R

router = APIRouter(prefix="/auth", tags=["认证"])

@router.post("/login", response_model=R[LoginResponse])
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    token, user_id = await auth_service.login(body.email, body.password)
    return R.ok(data=LoginResponse(access_token=token, user_id=user_id))
```

❌ 禁止在 API 路由中直接操作 ORM：

```python
# ❌ 反例：路由中直接 ORM 操作
@router.post("/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db)):
    user = await session.execute(select(User).where(User.email == body.email))
    user = user.scalar_one()
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401)
    return {"token": create_access_token(user.id)}
```

---

## 设计模式代码示例

> 详细模式说明见 [CLAUDE.md §设计模式与封装规范](../../CLAUDE.md#设计模式与封装规范强制)。

### 工厂模式（策略可切换场景）

```python
# app/services/splitter_factory.py
from typing import Protocol

class BaseSplitter(Protocol):
    def split(self, text: str) -> list[str]: ...

class LengthSplitter:
    def split(self, text: str) -> list[str]:
        # 第一步：按固定长度切分
        return [text[i:i+500] for i in range(0, len(text), 500)]

class TitleSplitter:
    def split(self, text: str) -> list[str]:
        # 第一步：按标题（#）切分
        return [s.strip() for s in text.split("#") if s.strip()]

# dict 映射替代 if/elif 链
SPLITTER_MAP: dict[str, type[BaseSplitter]] = {
    "length": LengthSplitter,
    "title": TitleSplitter,
}

def create_splitter(strategy: str) -> BaseSplitter:
    """工厂函数：根据策略名返回对应切片器实例"""
    cls = SPLITTER_MAP.get(strategy)
    if not cls:
        raise ValueError(f"Unknown splitter strategy: {strategy}, available: {list(SPLITTER_MAP)}")
    return cls()
```

### Client 封装（httpx 异步）

```python
# app/clients/base.py
import httpx
from loguru import logger

class BaseClient:
    """外部服务 Client 基类，统一超时、重试、异常处理"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        # 第一步：懒初始化连接（避免启动时阻塞）
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# app/clients/payment.py
from app.clients.base import BaseClient
from app.core.config import settings
from app.exceptions import ExternalServiceException

class PaymentClient(BaseClient):
    """支付服务 Client"""

    def __init__(self):
        super().__init__(settings.PAYMENT_API_URL, timeout=15.0)

    async def create_order(self, amount: float) -> dict:
        client = await self._get_client()
        # 第一步：发送请求
        # 第二步：统一异常处理（第三方异常 → 业务异常）
        try:
            resp = await client.post("/orders", json={"amount": amount})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Payment API returned {e.response.status_code}")
            raise ExternalServiceException(f"支付服务异常: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Payment API unreachable: {e}")
            raise ExternalServiceException("支付服务不可达")
```

### 工具类封装

```python
# app/utils/string_utils.py
import re

def to_snake_case(name: str) -> str:
    """CamelCase → snake_case"""
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# app/utils/date_utils.py
from datetime import datetime, timezone

def now_utc() -> datetime:
    """获取当前 UTC 时间（统一入口，禁止各处 datetime.now()）"""
    return datetime.now(timezone.utc)
```

---

## 统一响应体 R[T]

**强制**：所有 API 响应必须用 `R[T]` 包装，保持接口一致性。

```python
# schemas/common.py
from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar("T")

class R(BaseModel, Generic[T]):
    code: int = 0              # 0=成功，非0=错误
    message: str = "success"
    data: T | None = None
    trace_id: str | None = None  # 链路追踪 ID

    @classmethod
    def ok(cls, data: T, message: str = "success") -> "R[T]":
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, code: int, message: str) -> "R[T]":
        return cls(code=code, message=message, data=None)
```

---

## 全局异常处理

```python
# main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.exceptions import BizException
from app.schemas.common import R

app = FastAPI()

@app.exception_handler(BizException)
async def biz_exception_handler(request: Request, exc: BizException):
    return JSONResponse(
        status_code=exc.http_code,
        content=R.fail(code=exc.code, message=exc.message).model_dump(),
    )

# exceptions.py
class BizException(Exception):
    """业务异常基类"""
    http_code: int = 400
    code: int = 1000
    message: str = "业务错误"

class UnauthorizedException(BizException):
    http_code = 401
    code = 1001
    message = "未认证"

class NotFoundException(BizException):
    http_code = 404
    code = 1002
    message = "资源不存在"
```

---

## 依赖注入规范（Depends）

**强制**：跨层调用通过 Depends 注入，不在内部 `new` 对象。

```python
# api/deps.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session_factory
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

def get_user_repo(session: AsyncSession = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)

def get_auth_service(user_repo: UserRepository = Depends(get_user_repo)) -> AuthService:
    return AuthService(user_repo)
```

❌ 禁止：
- Service 内 `__init__` 中 `new` Repository
- Depends 链超过 4 层（重构信号）
- Depends 函数有副作用（写 DB / 发请求）

---

## Pydantic Schema 规范

```python
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class UserBase(BaseModel):
    email: str = Field(..., description="邮箱", examples=["user@example.com"])
    name: str = Field(min_length=1, max_length=50)

class UserCreate(UserBase):
    password: str = Field(min_length=8)

class UserVO(UserBase):
    model_config = ConfigDict(from_attributes=True)  # 允许从 ORM 转换
    id: int
    created_at: datetime
```

强制：
- 字段必须有 `description`（生成 OpenAPI 文档）
- ORM Model 的 `mapped_column()` 同样必须带 `comment=`，与 Schema `description` 对齐
- 复杂字段加 `examples`
- DTO（入参）和 VO（出参）分离，**禁止** 同一 Schema 兼用
- 严格模式下用 `Field(strict=True)`

---

## 异步任务规范

| 场景 | 推荐 |
|------|------|
| 轻量后台任务（发邮件、推送） | FastAPI `BackgroundTasks` |
| 异步任务队列（重试、调度） | **arq**（Redis 异步）或 **Celery 5.4+** |
| 定时任务 | **APScheduler** 或 **Celery Beat** |

❌ 禁止：长任务（>30s）放 `BackgroundTasks`（会阻塞 worker）。

---

## 异步数据库规范

详见 [dba.md](dba.md)。FastAPI 必须：

```python
# core/db.py
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # 防止 stale connection
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后仍可访问属性
)
```

---

## 接口文档规范（OpenAPI）

```python
# main.py
from fastapi import FastAPI

app = FastAPI(
    title="{Project} API",
    version="1.0.0",
    description="{项目描述} API",
    openapi_tags=[
        {"name": "认证", "description": "用户登录注册"},
        {"name": "对话", "description": "流式对话接口（SSE）"},
    ],
    docs_url="/docs",
    redoc_url="/redoc",
)
```

**强制**：
- 每个路由必须有 `summary` 和 `description`
- 标签按业务域分组
- 错误响应必须声明 `responses={400: {...}, 401: {...}, 500: {...}}`

---

## 安全规范

| 项 | 强制 |
|------|------|
| **CORS** | 显式声明 allowed_origins，**禁止** `allow_origins=["*"]`（生产） |
| **JWT** | 强制使用 HS256 / RS256，过期时间 ≤ 24h |
| **密码** | bcrypt / argon2 哈希，**禁止**明文 / MD5 / SHA1 |
| **限流** | slowapi 限流（如 `/login` 5次/分钟） |
| **输入校验** | Pydantic strict 模式 |
| **SQL 注入** | SQLAlchemy 参数化查询，**禁止** 字符串拼接 |
| **XSS** | 前端转义，API 返回 JSON 不渲染 HTML |
| **HTTPS** | 生产强制 TLS 1.2+ |
| **API Key** | 走 .env / Secret Manager，**禁止** 硬编码 |

---

## 日志规范（loguru + 结构化）

```python
# core/logging.py
import sys
from loguru import logger

# 移除默认 handler
logger.remove()
# 控制台：开发环境
logger.add(sys.stdout, level="DEBUG", serialize=False)
# 文件：生产环境，JSON 结构化 + 轮转
logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    level="INFO",
    serialize=True,  # JSON 输出
    rotation="100 MB",
    retention="30 days",
    compression="zip",
)
```

强制：
- 日志必须带 `request_id`（从中间件注入）
- 业务关键操作打 INFO，异常打 ERROR，调试打 DEBUG
- **禁止** 在日志中输出密码 / API Key / 用户 PII

---

## 事务规范

```python
# ✅ 正确：单请求单事务，由 Depends 控制
async def get_db_session():
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# ❌ 反例：手动管理事务，散落各处
@router.post("/order")
async def create_order(...):
    session = async_session_factory()
    session.begin()
    try:
        ...
        session.commit()
    except:
        session.rollback()
    finally:
        session.close()
```

事务失效陷阱：
- ❌ 在事务内做 HTTP 请求（`httpx.get`）→ 长时间持锁
- ❌ 在事务内调 LLM → 长时间持锁
- ❌ try/except 中吞掉异常导致无法回滚
- ✅ LLM / 外部 IO 放事务外，调 DB 放事务内

---

## 配置规范（Pydantic Settings）

```python
# core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "{ProjectName}"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str  # 必填，无默认值

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM（国产模型，**禁止使用任何国外 API**）
    # 主力：DeepSeek
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    LLM_DEFAULT_MODEL: str = "deepseek-chat"
    LLM_REASONER_MODEL: str = "deepseek-reasoner"
    # 备选：通义千问（阿里云百炼）
    DASHSCOPE_API_KEY: str | None = None
    LLM_BACKUP_MODEL: str = "qwen-plus"

    # Security
    JWT_SECRET: str
    JWT_EXPIRE_HOURS: int = 24

    # Langfuse
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None

settings = Settings()
```

`.env.example`（提交到 git，实际 `.env` 加入 `.gitignore`）：

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/{db_name}
# 主力：DeepSeek（必填）
DEEPSEEK_API_KEY=sk-xxx
# 备选：通义千问（可选）
DASHSCOPE_API_KEY=sk-xxx
JWT_SECRET=$(openssl rand -hex 32)
```

---

## SSE 流式响应规范

LLM 应用高频场景：

```python
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from app.llm.clients import get_llm
from app.agents.runner import stream_agent

@router.post("/chat/stream")
async def chat_stream(body: ChatRequest):
    """SSE 流式对话，事件类型：[PROGRESS] / [REFERENCE] / [CARD] / token"""
    async def event_generator():
        async for event in stream_agent(body.message, body.user_id):
            # 事件格式：data: {json}\n\n
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
```

事件类型与前端协议详见 [frontend.md §SSE 规范](frontend.md#sse-流式消息规范)。

---

## 测试规范

### 必须测试的场景清单

- [ ] API 路由：正常 / 异常 / 边界值
- [ ] Service：业务逻辑（mock Repository）
- [ ] Pydantic Schema：校验规则（min/max/email/regex）
- [ ] 权限：未登录 / 越权 / 角色不足
- [ ] 限流：触发熔断
- [ ] 异常：自定义异常 → 统一响应体
- [ ] LLM 调用：mock langchain `init_chat_model`（**禁止** 调真实 API；mock 模型为 `deepseek-chat`，**禁止** mock `gpt-4o` / `claude-*`）
- [ ] 数据库：testcontainers 启动临时 PG

### 测试示例

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.main import app
from app.core.db import get_db_session

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost:5432/test_db")
    async with engine.begin() as conn:
        # 创建表
        ...
    async with AsyncSession(engine) as session:
        yield session
    # 清理

# tests/test_auth.py
@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert "access_token" in data["data"]
```

---

## 禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **异步** | ❌ `async def` 路由中调用同步阻塞 IO；❌ LLM 调用无 timeout；❌ 跨请求持锁 |
| **依赖** | ❌ Service 内 `new` Repository；❌ Depends 链 > 4 层；❌ Depends 副作用 |
| **数据库** | ❌ 同步 session 与 async session 混用；❌ 事务跨 HTTP 请求；❌ 字符串拼接 SQL |
| **API** | ❌ 路由直接操作 ORM；❌ 同一 Schema 兼用 DTO/VO；❌ 路由无 `summary` |
| **安全** | ❌ 密码明文/MD5 存储；❌ CORS `allow_origins=["*"]`（生产）；❌ API Key 硬编码；❌ JWT 不设过期；❌ **调用任何国外 LLM API（OpenAI / Anthropic / Cohere / Jina）**；❌ **引入 `openai` / `anthropic` SDK 作为生产依赖** |
| **日志** | ❌ 日志输出密码/PII/API Key；❌ try/except 吞异常；❌ print 当日志 |
| **响应** | ❌ 返回 dict 不走 Pydantic；❌ 错误响应不用统一 R[T] |
| **测试** | ❌ 测试中调真实 LLM API；❌ 硬编码测试数据；❌ 测试无清理（污染 DB） |
| **配置** | ❌ 配置硬编码在代码里；❌ .env 提交到 git |
| **事务** | ❌ 事务内做 HTTP/LLM 调用；❌ 手动 try/commit/rollback（用 Depends） |
