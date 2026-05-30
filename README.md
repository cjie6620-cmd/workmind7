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
  集对话助手、知识库 RAG、任务 Agent、内容工作流、ERP 审批、Prompt 调试、用量监控于一体。
</p>

---

## ✨ 功能亮点

### 💬 智能对话助手
多轮上下文对话，流式实时输出，支持用户画像和角色切换，对话历史持久化到 PostgreSQL。

### 📚 知识库问答（RAG）
上传 PDF 文档，自动切片 + 向量化（bge-m3 Embedding），基于 pgvector 语义检索，回答带来源标注。

### 🤖 任务 Agent
基于 ReAct 推理框架，自动拆解任务、调用工具（天气、搜索、计算器等），执行过程可视化展示。

### ⚙️ 内容工作流（LangGraph）
内置周报生成、会议纪要、邮件撰写、PRD 编写等 LangGraph 工作流，多步骤编排、SSE 流式输出。

### 📋 ERP 智能审批
自然语言智能填单（报销 / 请假），Multi-Agent 模拟审批流程，支持多级审批和评论。

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
    <td align="center"><b>ERP 智能审批</b></td>
    <td align="center"><b>Prompt 调试</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/erp.png" alt="ERP审批" width="480"></td>
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
                      │  :5173 → :3000 (Vite Proxy)
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
| **向量存储** | pgvector (PostgreSQL) | 原生 SQL 向量检索，统一持久层 |
| **ORM** | SQLAlchemy 2.0 (async) | 异步 ORM，Mapped 类型注解 |
| **缓存** | Redis | 会话缓存、限流计数 |
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
│   └── vite.config.js            # Vite 配置（含 API 代理）
│
├── server-py/                    # Python 后端（FastAPI）
│   ├── app/
│   │   ├── routes/               # API 路由层（8 个模块）
│   │   │   ├── chat.py           # 对话接口（SSE 流式）
│   │   │   ├── knowledge.py      # 知识库接口（上传/检索）
│   │   │   ├── agent.py          # Agent 接口（ReAct + 工具）
│   │   │   ├── workflow.py       # 工作流接口（LangGraph）
│   │   │   ├── erp.py            # ERP 接口（填单 + 审批流）
│   │   │   ├── prompt.py         # Prompt 接口（A/B 测试）
│   │   │   ├── monitor.py        # 监控接口（统计 + 持久化）
│   │   │   ├── config.py         # 配置管理接口
│   │   │   └── health.py         # 健康检查
│   │   ├── services/             # 业务逻辑层
│   │   │   ├── chat/             # 对话 + 记忆管理
│   │   │   ├── agent/            # ReAct Agent + 工具集
│   │   │   ├── rag/              # 文档入库 + pgvector 检索
│   │   │   ├── erp/              # 表单解析 + 审批流引擎
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
| Redis | 7+ | 缓存（可选，不启动不影响核心功能） |
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

# Embedding 模型路径（本地 bge-m3）
EMBEDDING_MODEL=/path/to/bge-m3
```

> 完整配置项参考 [.env.example](server-py/.env.example)

### 3. 启动后端

```bash
cd server-py

# 创建虚拟环境
uv venv

# 激活虚拟环境
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 安装依赖
uv pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

启动成功后，API 文档访问：`http://localhost:3000/docs`

### 4. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

浏览器访问：`http://localhost:5173`

### 5. 数据库初始化

首次启动时，后端会自动完成以下初始化：

- ✅ 检测并启用 pgvector 扩展
- ✅ 自动创建数据表（documents、rag_chunks、conversations、approval_records、agent_configs、monitor_records）
- ✅ 填充默认配置种子数据（Prompt 模板、Agent 配置、工作流模板）

如需手动初始化：

```bash
cd server-py/scripts
psql -U <user> -d <database> -f init_pgvector.sql
```

---

## 📡 API 接口

所有接口前缀 `/api`，支持 SSE（Server-Sent Events）流式输出。

| 模块 | 路由前缀 | 核心功能 |
|------|---------|---------|
| 💬 对话 | `/api/chat` | 流式对话、会话管理、用户画像、角色设定 |
| 📚 知识库 | `/api/knowledge` | 文档上传 / 列表 / 删除、RAG 问答、分类管理 |
| 🤖 Agent | `/api/agent` | Agent 执行（SSE）、工具列表、预设示例 |
| ⚙️ 工作流 | `/api/workflow` | 模板列表、启动 / 恢复工作流（SSE） |
| 📋 ERP | `/api/erp` | 表单解析、审批流（SSE）、申请管理 |
| 🔧 Prompt | `/api/prompt` | 测试（SSE）、A/B 对比、模板 CRUD |
| 📊 监控 | `/api/monitor` | 统计看板、预算设置 |
| ⚙️ 配置 | `/api/configs` | Agent / 工作流 / Prompt 配置管理 |
| 🏥 健康检查 | `/health` | 存活检查、健康详情 |

> 完整接口文档启动后访问 [Swagger UI](http://localhost:3000/docs)

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

| 表 | 用途 |
|----|------|
| `documents` | 知识库文档元信息 |
| `rag_chunks` | 文档切片 + 向量嵌入（1024 维） |
| `conversations` | 对话历史记录 |
| `approval_records` | ERP 审批流程记录 |
| `agent_configs` | Agent / 工作流 / Prompt 配置 |
| `monitor_records` | LLM 调用监控数据 |

### 流式输出

对话、Agent、工作流、Prompt 测试均采用 SSE（Server-Sent Events）实时推送，前端逐字渲染，体验流畅。

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
uvicorn app.main:app --reload --port 3000   # 开发模式（自动重载）
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
