# ===== Flask 后端规范（单体架构） =====

> 适用场景：单个 Flask 应用，不涉及服务拆分、服务注册、网关等微服务概念

## 技术栈（必须遵守）

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 不用 3.11 以下 |
| uv | 0.7.x | 包管理 + 虚拟环境 + 运行，替代 pip + venv + pip-tools |
| Flask | 3.1.x | Pallets 出品，当前最新稳定线 |
| SQLAlchemy | 2.0.36+ | ORM，用新风格 `Mapped[type]` + `mapped_column()` |
| Flask-SQLAlchemy | 3.1.1 | Flask 集成层，要求 SQLAlchemy 2.0+ |
| Flask-Migrate | 4.1.0+ | 封装 Alembic 1.14.x，数据库迁移 |
| Flask-JWT-Extended | 4.7.1 | JWT 认证，支持 access+refresh token |
| Flask-Cors | 5.0.1 | 跨域处理 |
| Flask-Caching | 2.3.1 | 缓存扩展，Redis 后端 |
| redis-py | 5.x | Redis 客户端（不用 6.x，刚发布等生态验证） |
| Celery | 5.7.0+ | 异步任务队列，Redis 做 Broker |
| marshmallow | 3.x | 序列化/校验（不用 4.0，破坏性变更生态未适配） |
| marshmallow-sqlalchemy | 3.x | SQLAlchemy 模型自动序列化 |
| flask-smorest | 0.46.0 | OpenAPI 文档自动生成 |
| loguru | 0.7.3 | 日志，替代标准 logging |
| python-dotenv | 1.0.1 | .env 环境变量管理 |
| gunicorn | 22.x | Linux/Mac 生产 WSGI 服务器 |
| waitress | 2.x | Windows 兼容 WSGI 服务器 |

> 单体架构不需要：Nacos、Sentinel、Gateway、RocketMQ、服务注册发现

### 版本来源说明

以上版本均通过 **Context7 查询官方文档** 确认（2026-06）：
- Flask 3.1.1 → `pallets/flask` 官方版本列表
- SQLAlchemy 2.0.36+ → `sqlalchemy_en_20` 官方文档
- Flask-Migrate 4.1.0+ / Alembic 1.14+ → Flask-Migrate 官方兼容矩阵
- Pydantic v2（配合 marshmallow 使用时需注意版本隔离）

---

## 技术选型理由（半成品项目视角）

> 假设你已启动一个 Flask 单体项目（有代码骨架，业务逻辑逐步填充），以下解释每个技术组件在项目中**解决什么问题**。

### 核心框架层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **Flask 3.1** | Web 框架，处理 HTTP 请求/响应 | Pallets 出品，轻量、生态成熟、文档质量高。3.x 去掉了 Python 2 遗留代码，原生支持 Python 3.12+ |
| **Blueprint** | 路由模块化（按业务拆分） | Flask 原生方案，避免单个 `app.py` 膨胀到几千行 |
| **flask-smorest** | 自动生成 OpenAPI 3.0 文档 | 基于 marshmallow Schema 自动推导文档，零额外注解，`/docs` 即可调试 |

### 数据层

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **SQLAlchemy 2.0** | ORM，把 Python 对象映射到数据库表 | 2.0 的 `Mapped[type]` 写法自带类型提示，IDE 自动补全好，比旧 `Column()` 更安全 |
| **Flask-SQLAlchemy 3.1** | Flask 集成层（Session 管理、`db.paginate()`） | 自动绑定请求上下文，不用手动管理 Session 生命周期 |
| **Flask-Migrate 4.1 / Alembic 1.14** | 数据库迁移（表结构变更不丢数据） | 基于 Alembic，`flask db migrate` 自动生成迁移脚本，支持回滚 |
| **PyMySQL / asyncpg** | 数据库驱动 | PyMySQL 纯 Python 无编译依赖（开发友好），asyncpg 异步（FastAPI 场景用） |

### 认证与缓存

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **Flask-JWT-Extended 4.7** | JWT 认证（access + refresh token） | 内置 token 刷新、黑名单、用户加载钩子，比自己实现安全 |
| **Flask-Caching 2.3 + redis-py 5.x** | 缓存热点数据、接口防重 | Redis 后端性能最好，Flask-Caching 提供 `@cache.cached()` 装饰器 |
| **Flask-Cors** | 跨域处理 | 前后端分离必须，一行配置搞定 |

### 序列化与校验

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **marshmallow 3.x** | 入参校验 + 出参序列化 | 比 Pydantic 更适合 Flask 生态，flask-smorest 自动识别 Schema 生成文档 |
| **marshmallow-sqlalchemy 3.x** | Model → Schema 自动映射 | 省去手动写 Response Schema，自动从 ORM 模型提取字段 |
| **Pydantic v2** | 仅在需要强类型配置时使用 | Flask 生态首选 marshmallow，Pydantic 作为配置校验补充（不混用做序列化） |

### 异步任务

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **Celery 5.7 + Redis** | 异步任务队列（发邮件、数据同步、报表生成） | 比 BackgroundTasks 更可靠：支持重试、定时任务、失败回调，Redis 做 Broker 轻量够用 |

### 基础设施

| 组件 | 解决什么问题 | 为什么选它 |
|------|-------------|-----------|
| **loguru** | 日志 | 替代标准 logging，开箱即用：自动轮转、JSON 格式、装饰器异常捕获 |
| **gunicorn（Linux）/ waitress（Windows）** | 生产 WSGI 服务器 | 多 worker 进程处理并发，dev server 只能单线程 |
| **python-dotenv** | .env 环境变量管理 | 敏感信息不提交 git，开发/生产配置隔离 |

---

## 避坑清单

- marshmallow 必须用 3.x，4.0 是破坏性大版本，flask-smorest/marshmallow-sqlalchemy 兼容性存疑
- redis-py 用 5.x，6.x 刚发布生态待验证
- Flask-Migrate 必须在 `create_app()` 内部初始化，否则 `flask db` 命令找不到应用
- SQLAlchemy 2.0 禁止用 `Model.query`（已废弃），必须用 `db.session.execute(db.select(Model))`
- `db` 实例必须在 `extensions.py` 单独定义，禁止在路由文件里 `import db` 造成循环引用
- JWT_SECRET_KEY 必须从环境变量读取，禁止硬编码
- gunicorn 不支持 Windows，Windows 开发/部署用 waitress
- Celery Broker 和 Result Backend 都用 Redis，配置里必须写 `redis://` 不是 `redis+socket://`

## 开发命令

```bash
# 初始化项目（首次）
uv init my-project && cd my-project

# 添加依赖
uv add flask flask-sqlalchemy flask-migrate flask-jwt-extended flask-cors
uv add flask-caching redis celery marshmallow marshmallow-sqlalchemy flask-smorest
uv add loguru python-dotenv gunicorn waitress

# 添加开发依赖
uv add --dev pytest pytest-cov pytest-mock factory-boy ruff

# 启动开发服务器
uv run flask --app app run --debug

# 数据库迁移
uv run flask --app app db init
uv run flask --app app db migrate -m "描述"
uv run flask --app app db upgrade

# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run ruff format .

# 生产启动
uv run gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
```

## 项目结构（单体，按功能模块划分）

```
my-project/
├── app/
│   ├── __init__.py              # create_app() 应用工厂
│   ├── extensions.py            # db, migrate, jwt, cache 等扩展实例
│   ├── config.py                # Config 类（开发/测试/生产）
│   ├── common/                  # 公共模块
│   │   ├── __init__.py
│   │   ├── response.py          # 统一响应体 ok() / fail()
│   │   ├── exceptions.py        # BusinessException + 全局异常处理器
│   │   ├── decorators.py        # @permission_required 等自定义装饰器
│   │   └── utils.py             # 工具函数
│   ├── modules/                 # 业务模块（按功能拆分，不是按层）
│   │   └── xxx/
│   │       ├── __init__.py      # Blueprint 定义 + 注册路由
│   │       ├── routes.py        # 路由（对应 Controller）
│   │       ├── schemas.py       # marshmallow Schema（对应 DTO/VO）
│   │       ├── services.py      # 业务逻辑
│   │       └── enums.py         # 业务枚举
│   └── models/                  # SQLAlchemy 模型（全局共享）
│       ├── __init__.py          # 导入所有模型（确保 Alembic 能发现）
│       ├── base.py              # BaseModel（id, create_time, update_time, deleted）
│       ├── user.py
│       └── {entity}.py
├── migrations/                  # Alembic 迁移脚本（flask db 自动生成）
├── tests/                       # 测试
│   ├── conftest.py              # 公共 fixtures（app, client, db, auth_header）
│   ├── test_xxx.py
│   └── factories.py             # factory-boy 测试数据工厂
├── .env                         # 本地环境变量（不提交 git）
├── .env.example                 # 环境变量模板（提交 git）
├── pyproject.toml               # 项目配置 + 依赖
├── uv.lock                      # 依赖锁文件（提交 git）
└── README.md
```

## 分层规范（严格遵守）

### 路由层（Blueprint Routes — 对应 Controller）

- 只负责：接收请求 → 参数校验 → 调用 Service → 返回结果
- **禁止写任何业务逻辑**
- 使用 `Blueprint` + `@blp.route`（flask-smorest）
- 参数校验由 marshmallow Schema 自动完成
- 返回统一响应体

```python
from flask_smorest import Blueprint
from app.common.response import ok
from app.modules.{module}.schemas import {Entity}QuerySchema, {Entity}PageSchema, {Entity}SaveSchema
from app.modules.{module}.services import {Entity}Service

blp = Blueprint("{module}", __name__, url_prefix="/api/{module}", description="{模块描述}")


@blp.route("/list")
class {Entity}List(MethodView):
    @blp.arguments({Entity}QuerySchema, location="query")
    @blp.response(200, {Entity}PageSchema)
    def get(self, query_data):
        """分页查询{实体}列表，支持按名称、状态、时间范围筛选"""
        return {Entity}Service.list_{entities}(query_data)


@blp.route("/")
class {Entity}Create(MethodView):
    @blp.arguments({Entity}SaveSchema)
    @blp.response(201)
    def post(self, data):
        """创建{实体}，状态默认为"草稿"，需手动发布后才可见"""
        {Entity}Service.create_{entity}(data)
        return ok()
```

### Service 层

- **不需要接口 + 实现**（Python 不需要 Java 那套），直接写类方法或函数
- 所有业务逻辑在此层，核心业务编排层
- 数据库操作通过 SQLAlchemy Session 进行
- 禁止处理 HTTP 相关逻辑（不能 import request）

```python
from app.extensions import db
from app.models.{entity} import {Entity}
from app.common.exceptions import BizException


class {Entity}Service:
    @staticmethod
    def list_{entities}(query_data: dict) -> dict:
        # 第一步：构建查询条件
        stmt = db.select({Entity})
        if name := query_data.get("name"):
            stmt = stmt.where({Entity}.name.contains(name))
        # 第二步：执行分页查询
        page = db.paginate(stmt, page=query_data["page"], per_page=query_data["page_size"])
        # 第三步：返回分页结果
        return {"total": page.total, "list": page.items}

    @staticmethod
    def create_{entity}(data: dict) -> {Entity}:
        # 第一步：校验业务规则
        if {Entity}.query.filter_by(name=data["name"]).first():
            raise BizException("{实体}名称已存在")
        # 第二步：创建{实体}
        {entity} = {Entity}(**data)
        db.session.add({entity})
        db.session.commit()
        return {entity}
```

### Model 层（SQLAlchemy 2.0 新风格）

- 使用 `Mapped[type]` + `mapped_column()`（SQLAlchemy 2.0 推荐写法）
- 所有模型继承 `BaseModel`（含 id、create_time、update_time、deleted）
- 模型放在 `app/models/` 全局目录，**不在模块目录内**（避免循环引用）
- **所有 `mapped_column()` 必须带 `comment=` 参数**，描述字段业务含义（违反视为严重问题）

```python
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from app.extensions import db


class BaseModel(db.Model):
    """基础模型，所有业务表继承"""
    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")
    create_time: Mapped[datetime] = mapped_column(default=datetime.utcnow, comment="创建时间")
    update_time: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(default=False, comment="逻辑删除")


class {Entity}(BaseModel):
    __tablename__ = "{module}_{entity}"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False, comment="{实体名称}")
    status: Mapped[int] = mapped_column(default=0, comment="{状态枚举}")
    max_count: Mapped[int | None] = mapped_column(comment="{数量上限}")
    content: Mapped[str | None] = mapped_column(db.Text, comment="{详情}")
```

> **SQLAlchemy 2.0 `Mapped[T]` vs 旧 `Column()` 说明**
>
> | 特性 | 旧写法 `Column(String(100))` | 新写法 `Mapped[str]` + `mapped_column(String(100))` |
> |------|------|------|
> | 类型提示 | ❌ 无，IDE 无法推断 | ✅ `str` / `int` / `datetime` 自动推断 |
> | 可空性 | `nullable=True` 显式声明 | `Mapped[str | None]` 类型签名即表达 |
> | 默认值 | `default=xxx` 在 Column 参数里 | `mapped_column(default=xxx)` 更清晰 |
> | 官方推荐 | 2.0 仍支持，但不再推荐 | **SQLAlchemy 2.0 官方推荐写法** |
>
> 半成品项目如果已有旧写法模型，**不需要一次性全部迁移**，新模型用新写法即可，两种风格可以共存。

### Schema 层（marshmallow — 对应 DTO/VO）

- **入参 Schema**：校验 + 反序列化（对应 DTO）
- **出参 Schema**：序列化 + 字段过滤（对应 VO）
- 使用 `marshmallow-sqlalchemy` 的 `SQLAlchemyAutoSchema` 自动映射模型字段
- 禁止直接返回 Model 对象，必须通过 Schema 序列化

```python
from marshmallow import fields, validate
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from app.models.{entity} import {Entity}


class {Entity}SaveSchema(ma.Schema):
    """创建/修改{实体} — 入参校验"""
    name = fields.String(required=True, validate=validate.Length(min=1, max=50), metadata={"description": "{字段说明}"})
    type = fields.Integer(required=True, validate=validate.OneOf([1, 2, 3]), metadata={"description": "{类型枚举 1-xxx 2-xxx 3-xxx}"})
    start_time = fields.DateTime(required=True, metadata={"description": "开始时间"})
    end_time = fields.DateTime(required=True, metadata={"description": "结束时间，必须晚于开始时间"})
    max_count = fields.Integer(validate=validate.Range(min=1, max=999), metadata={"description": "{数量上限}"})
    cover_url = fields.String(metadata={"description": "封面图URL"})
    content = fields.String(metadata={"description": "{详情说明}"})


class {Entity}QuerySchema(ma.Schema):
    """{实体}分页查询 — 入参"""
    name = fields.String(metadata={"description": "{实体}名称（模糊搜索）"})
    status = fields.Integer(metadata={"description": "{实体}状态"})
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))


class {Entity}ResponseSchema(SQLAlchemyAutoSchema):
    """{实体}详情 — 出参"""
    class Meta:
        model = {Entity}
        fields = ("id", "name", "status", "max_count", "create_time")
        dump_only = ("id", "create_time")
```

> **flask-smorest + marshmallow 联动原理**
>
> 工作流程：
> 1. 路由方法上标注 `@blp.arguments({Entity}SaveSchema)` → 请求体自动反序列化 + 校验
> 2. 校验失败 → 自动返回 400 + 错误字段详情（无需手写 try/except）
> 3. 校验成功 → `data` 参数已是 dict，直接传给 Service
> 4. `@blp.response(200, {Entity}ResponseSchema)` → 响应自动序列化，过滤敏感字段
> 5. `smorest.init_app(app)` 时，自动生成 OpenAPI 3.0 JSON → 访问 `/docs` 即可看到
>
> **半成品项目下一步**：只需在路由上加装饰器，无需手写文档，Schema 即文档。

## 统一响应体

```json
{ "code": 200, "msg": "操作成功", "data": {} }
```

```python
# app/common/response.py
from flask import jsonify


def ok(data=None, msg="操作成功"):
    return jsonify({"code": 200, "msg": msg, "data": data})


def fail(msg="操作失败", code=400):
    return jsonify({"code": code, "msg": msg, "data": None}), code
```

## 全局异常处理

```python
# app/common/exceptions.py
from flask import jsonify
from marshmallow import ValidationError
from loguru import logger


class BizException(Exception):
    """业务异常"""
    def __init__(self, msg: str, code: int = 400):
        self.msg = msg
        self.code = code


def register_error_handlers(app):
    @app.errorhandler(BizException)
    def handle_biz(e):
        logger.warning(f"业务异常: {e.msg}")
        return jsonify({"code": e.code, "msg": e.msg, "data": None}), e.code

    @app.errorhandler(ValidationError)
    def handle_validation(e):
        msg = "; ".join(f"{k}: {v}" for k, v in e.messages.items())
        return jsonify({"code": 400, "msg": msg, "data": None}), 400

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.exception("系统异常")
        return jsonify({"code": 500, "msg": "系统繁忙，请稍后重试", "data": None}), 500
```

## 应用工厂（create_app）

```python
# app/__init__.py
from flask import Flask
from app.config import config
from app.extensions import db, migrate, jwt, cors, cache, smorest


def create_app(config_name: str = "development") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # 第一步：初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app)
    cache.init_app(app)
    smorest.init_app(app)

    # 第二步：注册蓝图
    from app.modules.{module1} import {module1}_blp
    from app.modules.{module2} import {module2}_blp
    app.register_blueprint({module1}_blp)
    app.register_blueprint({module2}_blp)

    # 第三步：注册全局异常处理
    from app.common.exceptions import register_error_handlers
    register_error_handlers(app)

    # 第四步：导入模型（确保 Alembic 能发现）
    from app import models  # noqa

    return app
```

## 扩展初始化（extensions.py）

```python
# app/extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_caching import Cache
from flask_smorest import Api

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
cache = Cache()
smorest = Api()
```

## 配置规范

```python
# app/config.py
import os
from datetime import timedelta


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "mysql+pymysql://root:123456@localhost:3306/{db_name}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_size": 10, "pool_recycle": 3600}

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Redis
    CACHE_TYPE = "RedisCache"
    CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Celery
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

    # API 文档
    API_TITLE = "{系统名称}"
    API_VERSION = "1.0.0"
    OPENAPI_VERSION = "3.0.3"


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    # 生产必须从环境变量读取，禁止用默认值
    SECRET_KEY = os.environ["SECRET_KEY"]
    JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
```

## 安全规范

- 使用 Flask-JWT-Extended 4.7.1
- Token 存客户端 Header：`Authorization: Bearer <token>`
- 支持 access + refresh 双 token
- 方法级权限：自定义 `@permission_required` 装饰器
- 敏感信息用环境变量，禁止明文配置
- 生产环境关闭 API 文档：`API_SPEC_OPTIONS = {"enabled": False}`
- CORS 配置白名单，禁止 `*`

## 日志规范

- 使用 loguru，禁止 `print()` 和标准 `logging`
- 请求日志：记录请求方法、路径、状态码、耗时
- 异常日志：`logger.exception("描述")` 自动带完整堆栈
- 操作日志：谁在什么时间做了什么（自定义装饰器 `@log_operation`）
- 生产环境日志写文件 + JSON 格式

```python
from loguru import logger
import sys

# 控制台输出（开发）
logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level} | {message}")

# 文件输出（生产）
logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    compression="gz",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{function}:{line} | {message}",
)
```

## Celery 异步任务规范

```python
# app/celery_app.py
from celery import Celery
from app.config import config
import os


def make_celery(app_name: str) -> Celery:
    celery = Celery(app_name)
    celery.config_from_object(config[os.getenv("FLASK_ENV", "development")], namespace="CELERY")
    return celery


celery = make_celery("{app_name}")

# 任务定义示例
@celery.task
def send_notification(user_id: int, message: str):
    """异步发送通知"""
    # 发送逻辑
    pass
```

> **Celery 工作流程说明（半成品项目下一步）**
>
> ```
> 路由层调用 → send_notification.delay(user_id, msg)
>                         ↓
>              Redis Broker（消息暂存）
>                         ↓
>              Celery Worker（独立进程，消费消息）
>                         ↓
>              执行 send_notification() 函数
>                         ↓
>              Redis Result Backend（存储结果，可选）
> ```
>
> **三个关键概念**：
> 1. **Broker**（消息中间件）：任务放这里排队，Redis 做 Broker 最轻量
> 2. **Worker**（执行进程）：`uv run celery -A app.celery_app worker --loglevel=info`，独立于 Flask 进程运行
> 3. **Result Backend**（结果存储）：可选，如果需要获取任务执行结果才配置
>
> **半成品项目启动 Celery 的步骤**：
> 1. 确保 Redis 已启动（`redis-server`）
> 2. 定义任务函数（加 `@celery.task` 装饰器）
> 3. 路由中调用 `task.delay(args)` 发送任务
> 4. 启动 Worker 消费任务

## Client 封装规范（Flask 同步场景）

> 详细规范见 [CLAUDE.md §Client 封装规范](../../CLAUDE.md#3-client-封装规范)。

```python
# app/clients/base.py
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

class BaseClient:
    """外部服务 Client 基类（同步），统一超时、重试、异常处理"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def _request(self, method: str, path: str, **kwargs) -> dict:
        # 第一步：发送请求
        # 第二步：统一异常处理（第三方异常 → 业务异常）
        url = f"{self.base_url}{path}"
        logger.debug(f"HTTP {method} {url}")
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"HTTP request failed: {e}")
            raise


# app/clients/{service}.py
from app.clients.base import BaseClient
from app.common.exceptions import BizException

class {Service}Client(BaseClient):
    """{服务} Client"""

    def __init__(self, base_url: str):
        super().__init__(base_url)

    def do_something(self, data: dict) -> dict:
        try:
            return self._request("POST", "/api/endpoint", json=data)
        except Exception as e:
            raise BizException(f"{服务}调用失败: {e}")
```

## 接口规范

- RESTful：`GET /api/{module}/{id}`、`POST`、`PUT`、`DELETE`
- 分页：`page` + `page_size`，返回 `{total, list}`
- 批量：`POST /api/{module}/batch`

## 测试规范

- pytest 8.x + pytest-mock 做单元测试
- Service 层覆盖率目标 80%+
- 测试命名：`test_should_期望行为_when_条件`

### 测试 fixtures（conftest.py）

```python
# tests/conftest.py
import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    app = create_app("testing")
    with app.app_context():
        yield app


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()


@pytest.fixture(scope="function")
def db(app):
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def auth_header(client, db):
    """登录后返回 Authorization header"""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    token = resp.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

### 测试用例示例

```python
# tests/test_{entity}.py
class Test{Entity}:
    def test_should_create_{entity}_when_valid_data(self, client, db, auth_header):
        resp = client.post("/api/{module}/", json={
            "name": "{测试数据}",
            "type": 1,
            "start_time": "2026-06-15T09:00:00",
            "end_time": "2026-06-15T17:00:00",
        }, headers=auth_header)
        assert resp.status_code == 201
        assert resp.get_json()["code"] == 200

    def test_should_fail_when_name_duplicate(self, client, db, auth_header):
        # 先创建一个
        client.post("/api/{module}/", json={"name": "{测试数据}", ...}, headers=auth_header)
        # 再创建同名
        resp = client.post("/api/{module}/", json={"name": "{测试数据}", ...}, headers=auth_header)
        assert resp.get_json()["code"] == 400

    def test_should_return_401_when_no_token(self, client, db):
        resp = client.get("/api/{module}/list")
        assert resp.status_code == 401
```

### 必须测试的场景清单

- 正常流程（Happy Path）
- 参数为 None / 空串 / 格式错误
- 边界值（最小值 / 最大值 / 超出范围）
- 业务异常（如名称重复、人数已满）
- 幂等性（重复调用同一接口结果一致）
- 未登录访问受保护接口（应返回 401）
- 权限不足（应返回 403）
