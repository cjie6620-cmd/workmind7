<p align="center">
  <img src="docs/logo.svg" alt="WorkMind AI" width="64" height="64">
</p>

<h1 align="center">WorkMind AI</h1>

<p align="center">
  <strong>企业级智能办公 Agent 平台</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Vue-3.4-4FC08D?logo=vue.js&logoColor=white" alt="Vue3">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangChain-0.3+-1C3C3C?logo=langchain&logoColor=white" alt="LangChain">
  <img src="https://img.shields.io/badge/License-MIT-blue" alt="License">
</p>

<p align="center">
  基于 Vue3 + FastAPI + LangChain + DeepSeek 构建的智能办公 Agent 系统，<br>
  集对话助手、知识库 RAG、任务 Agent、内容工作流、ERP AI 预审演练、Prompt 调试、用量监控于一体。
</p>

---

## ✨ 功能亮点

### 💬 智能对话助手
多轮上下文对话，流式实时输出，支持用户画像和角色切换，对话历史持久化到 PostgreSQL。

### 📚 知识库问答（RAG）
上传 PDF / TXT / Markdown 文档，自动切片 + 向量化（bge-m3 Embedding），基于混合检索（BM25 关键词 + pgvector 向量 + RRF 融合）+ CrossEncoder 精排（bge-reranker-v2-m3），回答带来源标注。

### 🤖 任务 Agent
基于 ReAct 推理框架，自动拆解任务、调用工具（天气、搜索、计算器等），执行过程可视化展示。

> **产品边界**：通知发送能力尚未接入，不能配置给 Agent；界面中的“未接入”工具不代表可执行能力。正式接入前需补充渠道权限、人工确认、幂等重试、回执和审计。

### ⚙️ 内容工作流（LangGraph）
内置周报生成、会议纪要、邮件撰写、PRD 编写等 LangGraph 工作流，多步骤编排、SSE 流式输出。

> **运行语义**：停用工作流配置会阻止新任务启动，不会追溯撤销已经受理或暂停的任务；这些任务可继续完成，或由用户显式取消。当前配置版本是乐观并发修订号，不提供历史版本仓库与一键回滚。

### 📋 ERP AI 预审演练
自然语言智能填单（报销 / 请假），通过 Multi-Agent 模拟多级审批和评论，用于方案预演与演示。

> **产品边界**：当前 ERP 模块不是正式审批系统，其结果不代表组织审批决定。接入真实业务前，仍需实现组织架构与真实审批人、待办流转、状态机、不可抵赖审计、撤回/转交/加签、通知和外部 ERP 对账等能力，并完成业务负责人验收。

### 🔧 Prompt 调试台
Prompt 模板版本管理，A/B 对比测试并排打分，流式输出实时预览。

### 📊 用量看板
Token 消耗、API 费用（USD / CNY）、缓存命中率、请求延迟、按模块统计，ECharts 可视化图表。

---

## 🖼 系统截图

<table>
  <tr>
    <td align="center"><b>智能对话</b></td>
    <td align="center"><b>知识库 RAG</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/chat.png" alt="智能对话" width="480"></td>
    <td><img src="docs/screenshots/knowledge.png" alt="知识库" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>任务 Agent</b></td>
    <td align="center"><b>内容工作流</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/agent.png" alt="任务Agent" width="480"></td>
    <td><img src="docs/screenshots/workflow.png" alt="工作流" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>ERP AI 预审演练</b></td>
    <td align="center"><b>Prompt 调试</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/erp.png" alt="ERP AI预审演练" width="480"></td>
    <td><img src="docs/screenshots/prompt.png" alt="Prompt调试" width="480"></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><b>用量看板</b></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="docs/screenshots/monitor.png" alt="用量看板" width="480"></td>
  </tr>
</table>

---

## 🏗 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (Vue3)                    │
│  ┌────────┬──────────┬────────┬────────┬───────────┐ │
│  │  Chat  │Knowledge │ Agent  │Workflow│ Monitor...│ │
│  └───┬────┴────┬─────┴───┬────┴───┬────┴─────┬─────┘ │
│      │         │         │        │          │       │
│      └─────────┴────┬────┴────────┴──────────┘       │
│                     │  Axios / SSE                    │
└─────────────────────┼────────────────────────────────┘
                      │  :5173 → :3001 (Vite Proxy)
┌─────────────────────┼────────────────────────────────┐
│              Backend (FastAPI)                        │
│                     │                                 │
│  ┌──────────────────┴──────────────────────┐         │
│  │            Middleware Layer              │         │
│  │      CORS · Rate Limit · Security       │         │
│  └──────────────────┬──────────────────────┘         │
│                     │                                 │
│  ┌──────┬───────┬───┴───┬────────┬───────┬────────┐  │
│  │ Chat │  RAG  │ Agent │Workflow│  ERP  │ Prompt │  │
│  │Service│Service│Service│Service │Service│Service │  │
│  └──┬───┴──┬────┴──┬────┴───┬────┴──┬────┴───┬────┘  │
│     │      │       │        │       │        │       │
│     │  ┌───┴───┐   │   ┌────┴──┐    │   ┌────┴────┐ │
│     │  │pgvector│   │   │LangGraph   │   │ A/B Test│ │
│     │  └───┬───┘   │   └────┬──┘    │   └─────────┘ │
│     │      │       │        │       │                 │
│  ┌──┴──────┴───────┴────────┴───────┴──────────┐     │
│  │           DeepSeek API (LLM)                │     │
│  │       Embedding: bge-m3 (Local)             │     │
│  │       Reranker: bge-reranker-v2-m3 (Local)  │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘
         │                    │
    ┌────┴─────┐        ┌────┴─────┐
    │PostgreSQL│        │  Redis   │
    │ +pgvector│        │ (Cache)  │
    └──────────┘        └──────────┘
```

---

## 🧰 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | Vue 3.4 + Vite 5 | Composition API，`<script setup>` 语法 |
| **UI 组件** | Element Plus 2.x + ECharts 5 | 企业级 UI 组件 + 数据可视化 |
| **状态管理** | Pinia | 轻量级全局状态 |
| **路由** | Vue Router 4 | 懒加载，历史模式 |
| **后端框架** | FastAPI 0.115+ | 异步高性能，自动 OpenAPI 文档 |
| **LLM 编排** | LangChain + LangGraph | Agent 推理、RAG 管线、工作流编排 |
| **模型** | DeepSeek API | Chat 模型，支持 Function Calling |
| **向量模型** | bge-m3 (本地) | 1024 维 Embedding，离线推理 |
| **精排模型** | bge-reranker-v2-m3 (本地) | CrossEncoder 重排序 |
| **检索策略** | BM25 + 向量混合检索 | EnsembleRetriever RRF 融合 |
| **向量存储** | pgvector (PostgreSQL) | 原生 SQL 向量检索，统一持久层 |
| **ORM** | SQLAlchemy 2.0 (async) | 异步 ORM，Mapped 类型注解 |
| **缓存与运行态** | Redis | 会话缓存、限流、预算原子账本、工作流快照与 Agent 报告 |
| **数据库** | PostgreSQL | 对话历史、审批记录、配置、监控数据 |

---

## 📂 项目结构

```
workmind7/
├── frontend/                     # Vue3 前端
│   ├── src/
│   │   ├── views/                # 页面组件（7 个模块）
│   │   │   ├── ChatView.vue      # 智能对话
│   │   │   ├── KnowledgeView.vue # 知识库管理
│   │   │   ├── AgentView.vue     # 任务 Agent
│   │   │   ├── WorkflowView.vue  # 内容工作流
│   │   │   ├── ErpView.vue       # 报销请假
│   │   │   ├── PromptView.vue    # Prompt 调试
│   │   │   └── MonitorView.vue   # 用量看板
│   │   ├── components/
│   │   │   ├── layout/           # 布局组件（Sidebar + Header）
│   │   │   └── common/          # 通用组件（Toast、ECharts）
│   │   ├── stores/               # Pinia 状态管理
│   │   ├── router/               # 路由配置
│   │   ├── utils/                # 工具函数（HTTP 封装）
│   │   └── styles/               # 全局样式 + CSS 变量
│   ├── package.json
│   ├── vite.config.js            # Vite 配置（含开发 API 代理）
│   ├── Dockerfile                # 生产多阶段构建
│   └── nginx.conf                # SPA / API / SSE 生产入口
│
├── server-py/                    # Python 后端（FastAPI）
│   ├── app/
│   │   ├── routes/               # API 路由层（8 个模块）
│   │   │   ├── chat.py           # 对话接口（SSE 流式）
│   │   │   ├── knowledge.py      # 知识库接口（上传/检索）
│   │   │   ├── agent.py          # Agent 接口（ReAct + 工具）
│   │   │   ├── workflow.py       # 工作流接口（LangGraph）
│   │   │   ├── erp.py            # ERP 接口（填单 + 预审演练）
│   │   │   ├── prompt.py         # Prompt 接口（A/B 测试）
│   │   │   ├── monitor.py        # 监控接口（统计 + 持久化）
│   │   │   ├── config.py         # 配置管理接口
│   │   │   └── health.py         # 健康检查
│   │   ├── services/             # 业务逻辑层
│   │   │   ├── chat/             # 对话 + 记忆管理
│   │   │   ├── agent/            # ReAct Agent + 工具集
│   │   │   ├── rag/              # 文档入库 + pgvector 检索
│   │   │   ├── erp/              # 表单解析 + 预审演练引擎
│   │   │   ├── prompt/           # 模板管理 + A/B 评分
│   │   │   ├── workflow/         # LangGraph 工作流定义
│   │   │   └── config/           # 配置服务 + 种子数据
│   │   ├── models/               # SQLAlchemy ORM 模型
│   │   ├── core/                 # 数据库连接 + Redis 客户端
│   │   ├── middleware.py         # 中间件（CORS、限流、安全）
│   │   ├── utils/                # 工具（日志、SSE、JSON 修复）
│   │   ├── config.py             # 配置管理（环境变量）
│   │   └── main.py               # FastAPI 入口
│   ├── scripts/                  # 数据库初始化脚本
│   ├── requirements.txt
│   └── .env.example              # 环境变量模板
│
└── README.md
```

---

## 🚀 快速启动

### 前置条件

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.11+ | 推荐 3.12 |
| Node.js | 18+ | 推荐 20 LTS |
| PostgreSQL | 14+ | 需安装 pgvector 扩展 |
| Redis | 7+ | 生产必需；开发模式可显式降级，但预算、工作流快照、报告等能力会受限 |
| uv | latest | Python 包管理器（`pip install uv`） |

### 1. 克隆项目

```bash
git clone https://github.com/your-username/workmind7.git
cd workmind7
```

### 2. 配置环境变量

```bash
cd server-py
cp .env.example .env
```

编辑 `.env` 文件，填入必要配置：

```ini
# 必填：DeepSeek API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 数据库连接（需已创建数据库并启用 pgvector 扩展）
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/workmind

# 模型配置
PRIMARY_MODEL=deepseek-chat

# 预算日界线、监控聚合和页面展示使用的 IANA 业务时区
BUSINESS_TIMEZONE=Asia/Shanghai

# Embedding 模型路径（本地 bge-m3）
EMBEDDING_MODEL=/path/to/bge-m3
```

> 完整配置项参考 [.env.example](server-py/.env.example)

### 3. 启动后端

```bash
cd server-py

# 创建虚拟环境（推荐 Python 3.12，避免 3.14 下部分包需本地编译）
uv venv --python 3.12

# 激活虚拟环境
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 安装依赖
uv pip install -r requirements.txt

# 首次启动及每次升级前执行数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

启动成功后，API 文档访问：`http://localhost:3001/docs`

### 4. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

浏览器访问：`http://localhost:5173`

### 5. 数据库迁移与启动初始化

数据库表结构使用 Alembic 管理。直接运行 `uvicorn` **不会自动创建表**；首次部署和每次版本升级都必须先执行：

```bash
cd server-py
alembic upgrade head
alembic current
```

表结构就绪后，应用启动会检查数据库与 pgvector，并在相应表为空时幂等填充默认配置和开发种子用户。容器镜像的 entrypoint 会在启动 API 前重试执行 `alembic upgrade head`。

`sql/init-db.sql` 仅保留给旧的本地空数据卷初始化流程；生产发布不要手工执行或用 `alembic stamp` 跳过迁移。已有数据库升级前必须备份，并在预发布环境验证升级、降级和再次升级。

### 6. 生产全栈部署

生产 Compose 会构建后端与前端，Nginx 提供 SPA fallback，并将 `/api` 和 `/health` 反向代理到后端；SSE 代理缓冲已关闭。

```bash
# 在仓库根目录执行
cp server-py/.env.example server-py/.env
# 编辑 server-py/.env：至少设置 DEEPSEEK_API_KEY、JWT_SECRET、生产 CORS 与账号配置

# 先检查最终配置，再构建并启动
docker compose --env-file server-py/.env -f docker/docker-compose.prod.yml config
docker compose --env-file server-py/.env -f docker/docker-compose.prod.yml up -d --build

# 验证前端容器和完整后端依赖状态
curl -f http://localhost:8080/healthz
curl -f http://localhost:8080/health/ready
```

默认入口为 `http://localhost:8080`，可通过 `FRONTEND_PORT` 修改。后端容器会在提供流量前完成迁移，前端会等待后端 readiness 通过。

生产上线仍需完成生产规模数据迁移与备份恢复、多 worker、真实 RAG 质量、容量与故障恢复验收；当前状态见 [生产就绪清单](docs/production-readiness.md)。

---

## 📡 API 接口

所有接口前缀 `/api`，支持 SSE（Server-Sent Events）流式输出。

| 模块 | 路由前缀 | 核心功能 |
|------|---------|---------|
| 💬 对话 | `/api/chat` | 流式对话、会话管理、用户画像、角色设定 |
| 📚 知识库 | `/api/knowledge` | 文档上传 / 列表 / 删除、RAG 问答、分类管理 |
| 🤖 Agent | `/api/agent` | Agent 执行（SSE）、工具列表、预设示例 |
| ⚙️ 工作流 | `/api/workflow` | 模板列表、启动 / 恢复工作流（SSE） |
| 📋 ERP AI 预审 | `/api/erp` | 表单解析、模拟审批流（SSE）、演练申请管理；不代表正式审批 |
| 🔧 Prompt | `/api/prompt` | 测试（SSE）、A/B 对比、模板 CRUD |
| 📊 监控 | `/api/monitor` | 统计看板、预算设置 |
| ⚙️ 配置 | `/api/configs` | Agent / 工作流 / Prompt 配置管理 |
| 🏥 健康检查 | `/health` | 存活检查、健康详情 |

> 完整接口文档启动后访问 [Swagger UI](http://localhost:3001/docs)

---

## 🔑 核心设计

### 分层架构

```
Route (请求接收 + 参数校验)
  ↓
Service (业务逻辑 + LLM 编排)
  ↓
Core (数据库 + 缓存 + 外部 API)
```

- **Route 层**：薄层，只做参数解析和响应格式化
- **Service 层**：核心业务逻辑，LLM 调用编排
- **Core 层**：数据库连接池、Redis 客户端、模型加载

### 数据持久化

所有数据统一存储在 PostgreSQL，利用 pgvector 实现向量检索：

知识库检索采用两阶段策略：第一阶段 BM25 关键词 + pgvector 向量双路召回，EnsembleRetriever 执行 RRF 融合；第二阶段 CrossEncoder（bge-reranker-v2-m3）精排过滤，确保最终结果的高相关性。

| 表 | 用途 |
|----|------|
| `documents` | 知识库文档元信息 |
| `rag_chunks` | 文档切片 + 向量嵌入（1024 维） |
| `conversations` | 对话历史记录 |
| `approval_records` | ERP 预审演练记录（非正式审批凭证） |
| `agent_configs` | Agent / 工作流 / Prompt 配置 |
| `monitor_records` | LLM 调用监控数据 |

### 流式输出

对话、Agent、工作流、Prompt 测试均采用 SSE（Server-Sent Events）实时推送，前端逐字渲染，体验流畅。

---

## 🧪 测试

### 后端（pytest）

```bash
# 中间件：docker compose -f docker/docker-compose.yml up -d
cd server-py
python -m pytest -m "not live and not slow" -q
```

### 前端（Vitest）

```bash
cd frontend
npm run test
npm run lint
npm run build
```

### Selenium 浏览器 E2E

```bash
# 先启动后端 :3001 与前端 :5173（或生产 Compose :8080）
cd e2e/selenium
pip install -r requirements.txt
set E2E_BASE_URL=http://127.0.0.1:5173
pytest -q
```

审计与关闭证据见 [docs/bug-audit-2026-07-17.md](docs/bug-audit-2026-07-17.md)。

---

## 📝 开发说明

### 前端开发

```bash
cd frontend
npm run dev      # 开发模式（热更新）
npm run build    # 生产构建
npm run preview  # 预览构建产物
```

### 后端开发

```bash
cd server-py
uvicorn app.main:app --reload --port 3001   # 开发模式（自动重载）
```

### 新增模块

1. **后端**：在 `routes/` 新增路由文件 → 在 `services/` 新增服务 → 在 `main.py` 注册路由
2. **前端**：在 `views/` 新增页面组件 → 在 `router/index.js` 注册路由 → 侧边栏自动展示

---

## 🤝 参与贡献

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交代码：`git commit -m 'feat: add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

---

## 📄 License

[MIT License](LICENSE)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/cjie6620-cmd">Mr. Chen</a>
</p>
