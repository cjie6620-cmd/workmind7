# DBA 规范（SQLAlchemy 2.0 async + Alembic + PGVector）

> 适用场景：Python + FastAPI 项目数据库设计、模型定义、迁移、seed 脚本。
>
> 与 [backend-fastapi.md](backend-fastapi.md)（Service/Repository 编排）/ [agent.md](agent.md)（向量库选型）协同。

---

## 命名规范（强制）

| 类别 | 规范 | 示例 |
|------|------|------|
| **表名** | snake_case，模块前缀 | `{module}_{entity}`、`{module2}_{entity2}` |
| **字段名** | snake_case | `user_id`、`created_at` |
| **主键** | `id` (BIGINT) | — |
| **外键** | `{关联表单数}_id` | `user_id`、`{entity}_id` |
| **时间字段** | `created_at` / `updated_at` / `deleted_at` | — |
| **布尔字段** | `is_xxx` / `has_xxx` | `is_active`、`has_paid` |
| **枚举字段** | `xxx_type` / `xxx_status` | `{entity}_status` |
| **索引** | `idx_{表}_{字段}` | `idx_{module}_{entity}_{field}` |
| **唯一索引** | `uk_{表}_{字段}` | `uk_user_email` |
| **多列索引** | 字段按查询频率排序 | `idx_a_b_c` |
| **迁移脚本** | `{revision}_{slug}.py` | `001_initial.py` |

---

## SQL 规范

强制：
- 关键字 / 保留字大写：`SELECT id, name FROM users WHERE active = true`
- 表名 / 字段小写
- 显式 `as` 别名
- 多表 join 必带表别名
- 禁止 `SELECT *`，必须列字段
- 禁止 MySQL 风格的反引号
- 分页用 `LIMIT/OFFSET`（小数据）或 keyset pagination（大数据）

---

## SQLAlchemy Model 规范（2.0 风格）

### 字段注释规范（强制）

所有 `mapped_column()` **必须**带 `comment=` 参数，描述字段业务含义。

✅ 正确：
```python
name: Mapped[str] = mapped_column(String(100), nullable=False, comment="用户姓名")
status: Mapped[int] = mapped_column(default=0, comment="状态 0-禁用 1-启用")
```

❌ 错误：
```python
name: Mapped[str] = mapped_column(String(100), nullable=False)  # 无 comment，违反规范
status: Mapped[int] = mapped_column(default=0)  # 无 comment，违反规范
```

### 强制使用 `Mapped[T]` 类型注解

```python
# models/base.py
from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, DateTime, String, func

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    """时间戳混入类"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class SoftDeleteMixin:
    """逻辑删除混入类"""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
```

### 标准 Model 示例

```python
# models/user.py
from sqlalchemy import String, Boolean, BigInteger, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, SoftDeleteMixin

class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "user"
    __table_args__ = (
        Index("uk_user_email", "email", unique=True),
        Index("idx_user_tenant_id", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    email: Mapped[str] = mapped_column(String(255), nullable=False, comment="邮箱地址")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户姓名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id"), nullable=False, comment="租户ID")

    # 关系
    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="joined", back_populates="users")
    conversations: Mapped[list["ChatConversation"]] = relationship(
        "ChatConversation", back_populates="user", lazy="selectin"
    )
```

### 模型文件组织

```
app/models/
├── __init__.py        # 统一导出所有 Model
├── base.py            # Base / Mixin
├── user.py
├── chat_conversation.py
├── chat_message.py
└── knowledge_segment.py
```

`__init__.py`：

```python
from app.models.base import Base
from app.models.user import User
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage

# Alembic autogenerate 需要从这里导入
__all__ = ["Base", "User", "ChatConversation", "ChatMessage"]
```

### 关联关系

| 关系类型 | `lazy=` 选择 | 说明 |
|----------|-------------|------|
| **多对一** (`ForeignKey`) | `joined`（小数据）/ `selectin`（集合） | 关联父表 |
| **一对多** (`relationship`) | `selectin`（避免 N+1） | 关联子表集合 |
| **多对多** | `selectin` | 关联表 |
| **一对一** | `joined` | 强制 join |

❌ 禁止：
- `lazy="select"`（默认）→ 触发 N+1 查询
- 跨 session 访问懒加载对象 → `MissingGreenlet` 错误
- `backref`（用 `back_populates` 显式双向关系）

### async session 访问懒加载

```python
# ❌ 反例：跨 session 访问 → MissingGreenlet
async def get_user_orders(user_id: int):
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        orders = user.orders  # 同步 IO，跨 event loop 错误
        return orders

# ✅ 正例：使用 selectinload 预加载
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_user_orders(user_id: int):
    async with async_session_factory() as session:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.orders))  # 一次查询加载
        )
        result = await session.execute(stmt)
        user = result.scalar_one()
        return user.orders  # ✅ 已加载，无 IO
```

---

## PGVector 向量列（LLM 应用核心）

### 启用 PGVector 扩展

```sql
-- migrations/xxx_enable_pgvector.py
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

### 向量列定义

```python
# models/knowledge_segment.py
from pgvector.sqlalchemy import Vector
from sqlalchemy import String, JSON, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class KnowledgeSegment(Base, TimestampMixin):
    __tablename__ = "knowledge_segment"
    __table_args__ = (
        # HNSW 索引（推荐，比 IVF 快）
        Index(
            "idx_knowledge_segment_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # 元数据索引（权限 / 版本过滤）
        Index("idx_segment_tenant_doc", "tenant_id", "doc_id"),
        Index("idx_segment_metadata", "metadata", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键ID")
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="切片唯一标识")
    parent_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="父切片ID")
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文档ID")
    doc_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False, comment="文档版本")
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="租户ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切片文本内容")
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False, comment="向量嵌入，维度与模型一致")
    accessible_by: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False, comment="可访问的用户/角色列表")
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, comment="元数据")
    expire_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="过期时间")
```

### 向量检索

```python
from sqlalchemy import select, func
from pgvector.sqlalchemy import L2Distance, CosineDistance

async def search_similar(
    session: AsyncSession,
    query_embedding: list[float],
    tenant_id: int,
    accessible_by: list[str],
    top_k: int = 5,
):
    # Cosine 距离（归一化向量等价于内积）
    distance = CosineDistance(KnowledgeSegment.embedding, query_embedding)

    stmt = (
        select(
            KnowledgeSegment,
            distance.label("score"),
        )
        .where(KnowledgeSegment.tenant_id == tenant_id)
        .where(KnowledgeSegment.accessible_by.contains(accessible_by))  # JSONB @>
        .where(KnowledgeSegment.expire_date.is_(None) | (KnowledgeSegment.expire_date > func.now()))
        .order_by(distance)
        .limit(top_k)
    )

    result = await session.execute(stmt)
    return result.all()
```

---

## JSONB 字段使用

```python
from sqlalchemy.dialects.postgresql import JSONB

class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extension: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="扩展元数据：版本、权限、变更日志等",
    )

# 索引（GIN）
__table_args__ = (
    Index("idx_doc_extension", "extension", postgresql_using="gin"),
)
```

---

## 迁移规范（Alembic 异步）

### 初始化（异步模式）

```bash
uv run alembic init -t async alembic
```

`alembic/env.py`（异步关键片段）：

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from app.core.config import settings
from app.models import Base  # 导入所有 Model

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### 迁移流程

```bash
# 自动生成迁移（必须人工 review！）
uv run alembic revision --autogenerate -m "add user table"

# 升级
uv run alembic upgrade head

# 降级 1 个版本
uv run alembic downgrade -1

# 查看历史
uv run alembic history
```

### 迁移脚本规则

1. **必须**在 `upgrade()` 和 `downgrade()` 都写明操作（可回滚）
2. 字段新增：用 `op.add_column` + 默认值 + 索引
3. 字段删除：先删索引/约束，再删列
4. **大表 ALTER**：用 `op.execute("ALTER TABLE ... ADD COLUMN ... DEFAULT ...")` 配合批量更新
5. **破坏性变更**（删列、改类型）：分多步迁移，先加新列、双写、再删旧列
6. **禁止**直接 `drop table`（必须先备份）
7. 索引创建：`postgresql_concurrently=True`（生产避免锁表）

```python
# ✅ 异步迁移示例
def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uk_user_email", "user", ["email"], unique=True)

def downgrade():
    op.drop_index("uk_user_email", table_name="user")
    op.drop_table("user")
```

### 迁移脚本检查清单（提交前必查）

- [ ] `upgrade()` 和 `downgrade()` 都已实现
- [ ] 字段有 `nullable` 约束
- [ ] 索引已创建（含唯一索引、复合索引）
- [ ] 外键有 `ondelete` 策略（CASCADE / RESTRICT）
- [ ] 默认值已设置（server_default 或 default）
- [ ] 字段类型正确（`String(N)` 显式长度、`DateTime(timezone=True)`）
- [ ] 大表操作用 `concurrently=True`
- [ ] 无 `drop table` 直接操作（先备份）
- [ ] 已在本地升级 / 降级 / 升级完整跑通

---

## Seed 脚本规范

```
scripts/
└── seed/
    ├── seed_dev.py         # 开发环境数据
    ├── seed_test.py        # 测试环境
    └── seed_prod.py        # 生产环境（谨慎）
```

```python
# scripts/seed/seed_dev.py
"""开发环境 seed 脚本

使用方式：uv run python scripts/seed/seed_dev.py
"""
import asyncio
from app.core.db import async_session_factory
from app.models.user import User
from app.core.security import hash_password

async def main():
    async with async_session_factory() as session:
        # 幂等：先查再插
        existing = await session.execute(select(User).where(User.email == "admin@example.com"))
        if existing.scalar_one_or_none():
            print("User already exists, skip")
            return

        user = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("admin123456"),
            is_active=True,
            tenant_id=1,
        )
        session.add(user)
        await session.commit()
        print(f"Created user: {user.id}")

if __name__ == "__main__":
    asyncio.run(main())
```

强制：
- Seed 脚本必须**幂等**（检查存在再插入）
- 密码用 `hash_password`（**禁止**明文）
- 生产 seed 单独文件 + 人工 review
- 大批量插入用 `bulk_save_objects` 或 `COPY`

---

## 自动执行规则

AI Agent 在执行以下任务时，**必须**自动加载本规范：

| 触发 | 行为 |
|------|------|
| 修改 `app/models/**/*.py` | 加载本规范 |
| 修改 Alembic 迁移脚本 | 加载本规范 |
| 创建/修改 `scripts/seed/*.py` | 加载本规范 |
| 涉及 PGVector 列 / 索引 | 加载本规范 |
| 设计数据库表结构 | 加载本规范 |

---

## 禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **命名** | ❌ 驼峰命名（用 snake_case）；❌ 表名无模块前缀；❌ 时间字段用 `create_time`（用 `created_at`） |
| **Model** | ❌ `lazy="select"` 默认值；❌ 跨 session 懒加载；❌ `backref`（用 `back_populates`）；❌ 不用 `Mapped[T]` 注解 |
| **SQL** | ❌ `SELECT *`；❌ 字符串拼接 SQL；❌ 同步 session 混入 async |
| **迁移** | ❌ 升级不写回滚；❌ 大表 ALTER 不分步；❌ 直接 `drop table`；❌ 不在本地跑通就合并 |
| **索引** | ❌ 外键无索引；❌ 大字段（text/jsonb）无 GIN 索引；❌ 生产用非 concurrently 索引 |
| **Seed** | ❌ 密码明文；❌ 脚本不幂等；❌ 生产 seed 不 review |
| **删除** | ❌ 物理删除（用 `SoftDeleteMixin` 逻辑删除） |
| **PGVector** | ❌ Embedding 维度与模型不一致；❌ 无 HNSW/IVF 索引；❌ 不带 metadata filter |
