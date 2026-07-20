# CLAUDE.md

> Python LLM 应用开发规范 — 适用于 FastAPI / Flask + RAG + Agent + LangChain/LlamaIndex 全栈项目。

---

## RAG 项目通用架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          用户交互层 (SSE)                                │
│         {API Controller} · {Web UI} · {IM Bot}                          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │          1. 意图识别                 │
              │   IntentRecognitionService (LLM)    │
              │   Structured Output → Record        │
              └────┬─────────────────────┬─────────┘
                   │ 不相关               │ 相关
           ┌───────▼───────┐    ┌────────▼────────────────────────────────┐
           │  通用对话      │    │           2. 查询改写                    │
           │  CommonChat   │    │  QueryTransformer (LLM)                │
           └───────┬───────┘    │  策略: 简洁/抽象/纠错/标准化              │
                   │            └────────┬────────────────────────────────┘
                   │         ┌───────────▼────────────────────────────────┐
                   │         │           3. 查询路由                       │
                   │         │  QueryRouter (LLM)                        │
                   │         │  {intent, strategy, confidence} → 路由决策  │
                   │         └──┬────────────┬────────────┬──────────────┘
                   │            │            │            │
                   │    ┌───────▼──┐   ┌─────▼────┐  ┌──▼──────────┐
                   │    │ 文档检索  │   │ 结构化查询│  │  图数据库    │
                   │    └───────┬──┘   └─────┬────┘  └──┬──────────┘
                   │            │            │           │
                   │            └────────────┼───────────┘
                   │              ┌──────────▼──────────────────────────┐
                   │              │  4. Reranking + 聚合                  │
                   │              │  ContentAggregator                   │
                   │              └──────────┬──────────────────────────┘
                   │              ┌──────────▼──────────────────────────┐
                   │              │  5. LLM 流式生成 + SSE 推送           │
                   │              │  · Prompt 动态注入（意图→领域 Prompt）  │
                   │              │  · [REFERENCE] 引用溯源事件            │
                   │              │  · [CARD] 结构化卡片事件               │
                   │              └─────────────────────────────────────┘
                   └────────────────────────────────────────────────────┘
```

### 文档入库通用流程

```
文件上传 → 格式转换 → 智能切片 → 向量化嵌入 → 索引存储
         (PDF/Word/Excel)  (Splitter)   (Embedding)  (ES/PG/Milvus)
                                    ↓
                              事件驱动自动触发
                              + 分布式锁并发保护
                              + 定时任务补偿兜底
```

---

## 角色规则索引（已归档）

> **2026-07-17 起**：仓库内 `.claude/roles/` 角色模板文件已移除，不再作为可加载路径。  
> 开发仍须遵守本文件其余章节（国产模型、分层、测试、安全、Prompt 管理等），以及 `docs/permissions.md`、`docs/production-readiness.md`。

> **模型合规约束（强制）**：所有 LLM 调用**必须使用国产大模型**（主力 **DeepSeek**，备选通义千问 / 智谱 GLM / 零一万物 / 豆包），**禁止使用任何国外 API**（OpenAI / Anthropic / Cohere / Jina / OpenRouter）。

### 任务特征 → 关注点（替代原 role 加载表）

| 任务类型 | 必查重点 |
|----------|----------|
| 前端 Vue / Pinia / SSE | 路由守卫、store 生命周期、`silent` 错误提示、DOMPurify |
| FastAPI 路由 / Service | 分层、owner/幂等、SSE 终态、预算守卫 |
| 模型 / Alembic / PGVector | 迁移可回滚、UTC-naive、文档 owner 隔离 |
| Docker / CI | Linux CPU 锁文件、Compose health、CI markers |
| RAG / Agent / Prompt | 检索隔离、断连不取消已受理任务、评测 markers |

---

## （以下原「角色协作 / 通用规则」仍有效；忽略对 `.claude/roles/*.md` 的链接）

### 通用规则（所有任务都遵守）

1. **命令式口吻，强约束**：使用「必须」「禁止」「不用」「强制」等强约束词，不使用「建议」「可以」「推荐」等弱约束词。
2. **❌/✅ 反例对照**：在关键设计/取舍点必须给出 ❌ 错误示例 + ✅ 正确示例。
3. **代码即规范**：所有代码片段必须可直接复制使用（包含完整 import、版本号、配置项）。
4. **版本固定**：技术栈表中的所有版本号必须精确（不能写"最新"），便于复现。
5. **跨文档引用**：优先引用本仓库 `docs/` 与本文件章节，不再依赖已删除的 `.claude/roles/*`。

### 通用规则（所有角色都遵守）

1. **命令式口吻，强约束**：使用「必须」「禁止」「不用」「强制」等强约束词，不使用「建议」「可以」「推荐」等弱约束词。
2. **❌/✅ 反例对照**：在关键设计/取舍点必须给出 ❌ 错误示例 + ✅ 正确示例。
3. **代码即规范**：所有代码片段必须可直接复制使用（包含完整 import、版本号、配置项）。
4. **版本固定**：技术栈表中的所有版本号必须精确（不能写"最新"），便于复现。
5. **文件末尾必有「禁止事项」**：每个 role.md 末尾必须包含「禁止事项」清单（与 `reviewer.md` / `frontend.md` 参考保持一致）。
6. **角色间引用**：跨角色引用使用 `[角色名](文件名.md#章节锚点)` 形式，形成「网状约束」。

### 注释规范（强制）

1. **实体字段注释**：ORM Model 的所有 `mapped_column()` 必须带 `comment=` 参数，描述字段业务含义；Pydantic / marshmallow Schema 字段必须带 `description`。两者缺一不可。
2. **分步注释**：涉及两步及以上逻辑的代码块，必须在对应代码行上方用 `# 第一步：xxx` / `# 第二步：xxx` 标注，清晰易懂，**禁止写在行尾**。

### 设计模式与封装规范（强制）

#### 1. 设计模式适用场景

| 模式 | 适用场景 | Python 实现方式 |
|------|---------|----------------|
| **工厂模式** | 多种策略可切换（切片器、序列化器、消息发送器） | 函数返回实例 / dict 映射 |
| **策略模式** | 同一接口多种算法（检索策略、改写策略、降级策略） | `Protocol` / `ABC` + 字典注册 |
| **装饰器模式** | 横切关注点（日志、权限、缓存、限流、重试） | Python 原生 `@decorator` |
| **观察者模式** | 事件驱动（入库完成→切片→向量化） | 回调函数 / `asyncio.Event` / 信号量 |
| **单例模式** | 全局共享资源（连接池、配置、LLM Client） | 模块级变量（Python 模块天然是单例） |
| **Repository 模式** | 封装数据访问，业务层不感知 SQL | 类封装 SQLAlchemy 查询 |
| **依赖注入** | 跨层解耦（API → Service → Repository） | FastAPI `Depends` / Flask 参数传递 |

> **原则**：用对场景才用模式，**禁止过度设计**——为不存在的需求预留模式是反模式。

#### 2. 工具类封装原则

- 同一功能出现 **≥ 2 次** → 必须提取到 `common/utils.py` 或 `app/utils/`
- 工具函数必须**无状态、无副作用、纯函数**（输入→输出）
- 按职责拆分文件：`string_utils.py`、`date_utils.py`、`file_utils.py`
- **禁止**在工具函数中 import 业务模块（避免循环依赖）

#### 3. Client 封装规范

所有外部服务调用**必须**通过 Client 类封装，**禁止**在 Service 层直接调用第三方 SDK。

强制要求：
- 统一放在 `app/clients/` 或 `app/infra/` 目录
- **统一初始化**：配置从 Settings 注入，不在 Client 内部硬编码
- **统一异常处理**：捕获第三方异常，转为业务异常
- **超时和重试机制**：必须配置 timeout，关键接口加重试
- **日志记录**：请求/响应/异常必须有日志

### 中间件与测试环境管理规范（强制）

#### 1. 新增中间件时（必须按顺序执行）

新增任何中间件（Redis、PostgreSQL、Qdrant、MinIO 等），AI Agent 必须**主动**完成以下步骤：

1. **检查端口占用**：启动前检查目标端口是否已被占用，占用则提示用户确认是否停用现有服务
2. **编写 docker-compose 配置**：在 `docker-compose.yml` 中添加服务定义，包含 image、ports、volumes、healthcheck
3. **拉取镜像并启动**：执行 `docker compose up -d {service_name}`，等待容器启动
4. **健康检查**：验证服务端口可访问、healthcheck 通过
5. **记录端口和连接方式**：在 `.env.example` 中补充对应的连接地址和端口

❌ 禁止：写完 docker-compose 不启动、启动后不验证健康检查、不更新 `.env.example`

#### 2. 代码改动需要测试时（必须主动判断）

代码改动后需要运行测试，AI Agent 必须**主动**执行：

1. **检查测试依赖端口**：确认测试所需的中间件（DB、Redis 等）是否正在运行
2. **端口冲突判断**：
   - 端口空闲 → 直接启动服务再测试
   - 端口被占用但服务正常 → 直接测试
   - 端口被占用且服务异常 / 版本不对 → 提示用户确认后关闭重启
3. **执行测试**：确认环境就绪后才运行测试命令
4. **测试后清理**：如果是临时启动的测试服务，测试完成后询问用户是否关闭

❌ 禁止：盲目运行测试不管环境、端口冲突时静默跳过、测试后不清理临时容器

### 技术栈速查（全局）

> 详细版本与说明见各角色文件。

| 域 | 技术 | 版本 |
|----|------|------|
| **语言** | Python | 3.12+ |
| **包管理** | uv | latest |
| **Web 框架** | FastAPI / Flask | 0.136+ / 3.1+ |
| **数据校验** | Pydantic | v2 |
| **ORM** | SQLAlchemy | 2.0 (async) |
| **迁移** | Alembic | latest |
| **向量库** | Milvus / Qdrant / PGVector | 视场景 |
| **LLM 框架** | LangChain / LlamaIndex / LangGraph | 1.0+ |
| **LLM 主力** | **DeepSeek**（deepseek-chat / deepseek-reasoner） | langchain-deepseek 0.1+ |
| **LLM 备选** | 通义千问 / 智谱 GLM / 零一万物 / 豆包 | 视场景 |
| **LLM 国外 API** | **❌ 禁止**（OpenAI / Anthropic / Cohere / Jina / OpenRouter 全部禁用） | — |
| **Agent 框架** | LangGraph（生产）/ smolagents（轻量） | latest |
| **可观测** | Langfuse | 2.x |
| **Guardrails** | Guardrails AI | latest |
| **前端** | Vue 3.4+ / Vite 5+ / Pinia / Ant Design Vue | latest |
| **数据库** | PostgreSQL 16+ (with pgvector) | 16+ |
| **缓存** | Redis 7+ | 7+ |
| **对象存储** | MinIO | latest |
| **消息队列** | Redis Stream / RabbitMQ / Kafka | 视场景 |
| **监控** | Prometheus + Grafana | latest |
| **部署** | Docker Compose + GPU 编排 | latest |

### 角色协作流程（AI Agent 自主判断）

AI Agent 收到任务后，**必须**自主完成以下判断，而不是按固定顺序执行：

1. **分析任务特征**：识别任务涉及哪些技术领域（前端 / 后端 / 数据库 / 部署 / RAG / Agent）
2. **查阅「任务特征 → 角色自动加载映射表」**：根据任务关键词，确定需要加载哪些 role.md
3. **按依赖顺序加载**：如果涉及多角色协作，按数据流方向加载（设计 → 实现 → 数据 → 测试 → 部署 → 审查）
4. **执行时引用规范**：每个实现步骤必须参照对应 role.md 中的规范和示例
5. **涉及中间件时**：先查阅 `devops.md`，按「中间件与测试环境管理规范」执行端口检查和容器启动

❌ 禁止：不加载任何 role.md 就开始写代码、跳过关键角色（如 RAG 任务不加载 `agent.md`）

### 新增角色文件使用指引（2026-06 补充）

本项目新增了四个关键领域的角色规范，覆盖 LLM 应用开发的核心环节：

#### 1. Prompt Engineering 规范

**何时加载**：
- 设计新的 Prompt 模板时
- 优化现有 Prompt 效果时
- 设计 Few-shot 示例时
- 编写 RAG 场景的 Prompt 时

**核心价值**：
- 10 条核心设计原则（基于 OpenAI/Anthropic/Google 三家共识）
- 10 种常用 Prompt 模式（Zero-shot / Few-shot / CoT / ReAct / Structured Output 等）
- RAG 场景 Prompt 优化策略（检索前 Query 改写、检索后上下文注入、减少幻觉）
- 10 大反模式（避免踩坑）
- 国产模型（DeepSeek 等）适配建议

**典型场景**：
```
任务：设计意图识别 Prompt
加载：prompt-engineering.md
参考：§二 核心设计原则、§三 Few-shot 模式、§四 RAG 场景优化
```

#### 2. MCP 规范

**何时加载**：
- 开发新的 MCP Server 时
- 设计 MCP Tool 接口时
- 将 MCP 集成到 Agent 架构时
- 调试 MCP Tool 调用问题时

**核心价值**：
- MCP 核心架构（Host-Client-Server 三层模型）
- 三大原语（Tool / Resource / Prompt）
- Python FastMCP 开发模式（完整代码示例）
- MCP Tool 设计原则（命名、描述、错误处理、分页）
- MCP 与 LangGraph/LangChain 集成模式

**典型场景**：
```
任务：开发文档检索 MCP Server
加载：mcp.md
参考：§四 MCP Server 开发规范、§五 MCP Tool 设计原则
```

#### 3. Skill 规范

**何时加载**：
- 创建新的 Skill 时
- 优化 Skill 触发准确率时
- 设计 Skill 与 Agent 工作流集成时
- 调试 Skill 加载/执行问题时

**核心价值**：
- Skill 本质定义（Tool = 手，Skill = 脑中的专业知识）
- 渐进式披露（Progressive Disclosure）三级加载机制
- Action-First 原则（给可执行代码，不是概念知识）
- SKILL.md 结构模板（name / description / When to use / How to do / Gotchas）
- Skill 与 Tool / MCP / Subagent / Hook 的集成模式

**典型场景**：
```
任务：创建数据处理 Skill
加载：skill.md
参考：§二 核心设计原则、§四 SKILL.md 结构、§六 高质量 Skill 的 Checklist
```

#### 4. RAG 评测规范

**何时加载**：
- 设计 RAG 评测指标体系时
- 编写 RAG 评测流水线时
- 配置 CI 回归门禁时
- 分析 RAG 评测结果时

**核心价值**：
- RAGAS 核心指标详解（Faithfulness / ContextPrecision / ContextRecall / FactualCorrectness）
- RAGAS Collections API 使用方式（Python 代码示例）
- 评测数据集设计规范（50~100 条 golden dataset，覆盖四类查询）
- CI/CD 集成与回归门禁（pytest 集成、阈值设定、Pipeline 配置）
- RAGAS vs DeepEval 选型对比

**典型场景**：
```
任务：配置 RAG 评测流水线
加载：rag-evaluation.md
参考：§五 RAGAS 使用方式、§七 CI/CD 集成与回归门禁、§九 常见陷阱与最佳实践
```

#### 四个新角色的协作关系

```
Prompt Engineering ←→ Agent（Prompt 模板版本管理）
        ↓
MCP Server ←→ Agent（Tool 暴露和调用）
        ↓
Skill ←→ Agent（领域知识编排）
        ↓
RAG Evaluation ←→ Agent（质量保障和迭代）
```

**关键理解**：
1. **Prompt Engineering** 是基础：好的 Prompt 是 RAG 和 Agent 效果的前提
2. **MCP** 是 Tool 层标准化：让 Tool 生态可复用、可组合
3. **Skill** 是知识层标准化：让 Agent 领域知识模块化、可维护
4. **RAG Evaluation** 是质量保障：用数据驱动迭代，避免"改了就上线"的赌博

**禁止事项**：
❌ 不加载 prompt-engineering.md 就设计 Prompt（容易踩反模式坑）
❌ 不加载 mcp.md 就开发 MCP Server（Tool 描述写太烂、不声明 annotations）
❌ 不加载 skill.md 就创建 Skill（违反渐进式披露、Action-First 原则）
❌ 不加载 rag-evaluation.md 就配置 RAG 评测（指标选错、阈值不设、门禁不配）

---

## 开发命令速查

#### 项目初始化

```bash
uv init my-project && cd my-project
```

#### 依赖管理

```bash
uv add fastapi sqlalchemy              # 添加生产依赖
uv add --dev pytest ruff mypy          # 添加开发依赖
```

#### 开发运行

```bash
uv run uvicorn app.main:app --reload --port 8000   # FastAPI
uv run flask --app app run --debug                  # Flask
```

#### 测试

```bash
uv run pytest                        # 全部测试
uv run pytest tests/test_user.py     # 单文件
uv run pytest -k "test_login"        # 关键字过滤
uv run pytest --cov=app              # 覆盖率报告
```

#### 代码质量

```bash
uv run ruff check .                  # Lint 检查
uv run ruff format .                 # 自动格式化
uv run mypy app/                     # 类型检查
```

#### 数据库迁移（Alembic）

```bash
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
uv run alembic downgrade -1
```

---

## 错误处理与重试规范（强制）

### 1. 分层异常体系

所有异常必须继承统一基类，**禁止**裸 `except Exception`：

| 异常类型 | HTTP 状态码 | 场景 |
|----------|-----------|------|
| `BizException` | 400 | 业务校验失败 |
| `UnauthorizedException` | 401 | 未认证 |
| `NotFoundException` | 404 | 资源不存在 |
| `ExternalServiceException` | 502 | 第三方服务异常 |
| `LLMException` | 503 | LLM 调用失败 |

### 2. LLM 调用重试（tenacity）

LLM API 调用**必须**配置重试，只重试可恢复错误：

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

@retry(
    retry=retry_if_exception_type((RateLimitError, TimeoutError, ConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),  # 指数退避，防止雪崩
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def call_llm(prompt: str) -> str:
    # 第一步：发送请求到 LLM API
    # 第二步：解析响应，失败则 tenacity 自动重试
    ...
```

❌ 禁止：重试 400/401/403（不可恢复错误）、无上限重试、重试无日志

### 3. 降级策略

关键链路必须有降级方案：
- LLM 主力模型不可用 → 切换备用模型（如 `deepseek-chat` → `qwen-plus`）
- 向量库不可用 → 降级为全文检索
- 第三方 API 不可用 → 返回缓存结果或默认值

---

## 代码风格与 Lint（强制）

| 项 | 规范 | 工具 |
|----|------|------|
| **格式化** | PEP 8，行宽 120 | `ruff format` |
| **Lint** | 零 warning | `ruff check` |
| **类型检查** | 所有公开函数必须有类型注解 | `mypy --strict` |
| **命名** | 变量/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE` | ruff 规则 |
| **导入排序** | 标准库 → 第三方 → 本地，组间空行 | `ruff check --select I` |

强制：
- CI 流水线必须跑 `ruff check` + `mypy`，不通过禁止合并
- 新增代码禁止引入 `# type: ignore`（除非有明确理由并注释说明）
- 禁止 `print()` 调试（用 `logger.debug`）

---

## 版本核实机制（强制）

> 确保所有规范文件中的 AI/技术库版本不落后于官方最新版。

### 规则

1. 所有 AI 相关角色文件顶部**必须**有"最后核对日期"
2. 复核周期：每季度（3/6/9/12 月）
3. 核查工具：**Context7**（`mcp__context7__resolve-library-id` + `mcp__context7__query-docs`）
4. 核查对象：LangChain / LangGraph / RAGAS / MCP SDK / FastAPI / Pydantic

### 核查流程

1. 对每个关键库调用 Context7 查询最新版本
2. 对比规范中写的版本，落后 > 1 个小版本则标记为"需更新"
3. 有破坏性变更（major version bump）**必须**更新代码示例

### 版本落后分级

| 落后程度 | 处理 |
|---------|------|
| patch 版本落后（如 1.0.1 → 1.0.3）| 记录，低优先级 |
| minor 版本落后（如 0.4 → 0.5）| 评估 breaking change，中优先级 |
| major 版本落后（如 0.x → 1.0）| **[严重]** 必须立即更新代码示例 |

### 自动化核查

> 原 `scripts/check_versions.py` 已随角色文件一并移除。季度复核改为人工执行：
> 用 Context7 查询各关键库最新版本，与本文件「技术栈速查」表比对并更新。

---

## 安全规范（强制）

| 项 | 规范 |
|----|------|
| **API Key** | 必须走 `.env` / Secret Manager，**禁止**硬编码或提交 git |
| **密码存储** | bcrypt / argon2 哈希，**禁止**明文 / MD5 / SHA1 |
| **SQL 注入** | SQLAlchemy 参数化查询，**禁止**字符串拼接 |
| **XSS** | API 返回 JSON，前端负责转义 |
| **CORS** | 显式声明 `allowed_origins`，**禁止**生产环境 `allow_origins=["*"]` |
| **Prompt 注入** | 用户输入必须消毒后再拼入 Prompt，禁止直接拼接 |
| **HTTPS** | 生产强制 TLS 1.2+ |
| **JWT** | HS256/RS256，过期时间 ≤ 24h，必须设 refresh token |
| **依赖审计** | 定期 `uv audit` 或 `pip-audit`，修复高危漏洞 |

---

## 测试策略（强制）

### 测试分层

| 层 | 工具 | 覆盖率目标 | 说明 |
|----|------|-----------|------|
| **单元测试** | pytest + pytest-mock | Service 层 80%+ | 纯函数、业务逻辑 |
| **集成测试** | pytest + httpx AsyncClient | API 路由 60%+ | 端到端 HTTP 测试 |
| **E2E 测试** | testcontainers + 真实 DB | 关键路径 | 需启动中间件 |

### LLM 测试规范

- **禁止**测试中调真实 LLM API（耗时 + 费用 + 不确定性）
- **必须** mock LLM 返回值，mock 模型为 `deepseek-chat`，**禁止** mock `gpt-4o` / `claude-*`
- 离线评估用 golden dataset（固定输入→期望输出），用 `ragas` / `deepeval` 评分

### 测试命名

```
test_should_{期望行为}_when_{条件}
```

示例：`test_should_return_401_when_no_token`

---

## Git 工作流规范

### Commit 规范（Conventional Commits）

```
<type>(<scope>): <description>
```

类型：`feat` / `fix` / `refactor` / `test` / `docs` / `chore` / `perf`
示例：`feat(auth): add JWT refresh token support`

### 分支命名

- 主分支：`main`（保护分支，禁止直接 push）
- 功能分支：`feat/{feature-name}`
- 修复分支：`fix/{bug-description}`
- 热修复：`hotfix/{issue}`

### PR 规范

- 标题 ≤ 70 字符，使用 Conventional Commits 格式
- 必须有 description（做了什么 + 为什么）
- CI 全部通过才能合并
- 至少 1 人 approve

---

## Prompt 管理规范（强制）

LLM 应用中 Prompt 是核心资产，必须规范管理：

### 存储规范

- Prompt **必须**以文件形式存储（`.txt` / `.jinja2` / `.yaml`），**禁止**硬编码在 Python 代码中
- 统一放在 `prompts/` 或 `app/prompts/` 目录，按业务域命名：`{domain}-{action}-prompt.txt`
- 使用 Jinja2 模板语法注入变量：`{{ user_query }}`，禁止 f-string 拼接

### 版本管理

- Prompt 文件纳入 Git 版本控制
- 修改 Prompt 必须在 commit message 中说明变更原因
- 重大 Prompt 变更需 A/B 测试验证效果后再上线

### 安全要求

- Prompt 模板中必须有输入消毒占位符：用户输入先过滤再注入
- 禁止在 Prompt 中暴露系统架构、内部 API、数据库结构等敏感信息

---

## 参考资源索引（集中管理，不重复）

> 各角色文件中不再单独列出参考来源，统一在此管理。

### AI/LLM 权威来源

- OpenAI Prompt Engineering: https://platform.openai.com/docs/guides/prompt-engineering
- Anthropic Prompt Engineering: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/
- Google Prompting Strategies: https://ai.google.dev/gemini-api/docs/prompting-strategies
- LangChain: https://python.langchain.com/
- LangGraph: https://langchain-ai.github.io/langgraph/
- RAGAS: https://docs.ragas.io/
- MCP Specification: https://spec.modelcontextprotocol.io/
- DeepSeek API: https://platform.deepseek.com/api-docs
- 通义千问: https://help.aliyun.com/zh/model-studio/

### 工具

- LangChain Prompt Hub: https://smith.langchain.com/hub
- Context7: 用于查询最新官方文档（MCP 工具 `mcp__context7__resolve-library-id` + `mcp__context7__query-docs`）
- Langfuse: https://langfuse.com/
- MCP Inspector: 调试 MCP Server 的可视化工具

