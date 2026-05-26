# WorkMind AI — 智能办公 Agent 平台

基于 Vue3 + LangChain + DeepSeek 构建的智能办公 Agent 系统。提供 Node.js 和 Python 两套后端实现。

## 项目模块

| 模块 | 说明 | 状态 |
|------|------|------|
| 智能对话助手 | 多轮对话 / 流式输出 / 用户画像 | ✅ 已完成 |
| 知识库问答   | 文档上传 / RAG 检索 / 来源标注 | ✅ 已完成 |
| 任务 Agent   | Function Call / ReAct / 工具可视化 | ✅ 已完成 |
| 内容工作流   | 周报/纪要/邮件/PRD 工作流 | ✅ 已完成 |
| ERP 报销请假 | 智能填单 / Multi-Agent 审批 | ✅ 已完成 |
| Prompt 调试  | A/B测试 / 版本管理 | ✅ 已完成 |
| 用量看板     | Token消耗 / 费用 / 缓存统计 | ✅ 已完成 |

## 技术栈

- **前端**：Vue3 + Vite + Pinia + Vue Router
- **后端（Node.js）**：Express + LangChain.js + LangGraph
- **后端（Python）**：FastAPI + LangChain + LangGraph
- **模型**：DeepSeek（对话）/ 智谱（Embedding）
- **向量库**：Chroma
- **部署**：Docker + docker-compose

## 快速启动

### 1. 克隆项目

```bash
git clone <repo-url>
cd workmind7
```

### 2. 配置环境变量

```bash
# Node.js 版
cd server
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# Python 版
cd server-py
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 启动后端

**Node.js 版：**

```bash
cd server
npm install
npm run dev
# 服务启动在 http://localhost:3000
```

**Python 版：**

```bash
cd server-py
pip install -r requirements.txt
uvicorn app.main:app --port 3000 --reload
# 服务启动在 http://localhost:3000
# API 文档：http://localhost:3000/docs
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
# 页面打开在 http://localhost:5173
```

### 5. （可选）启动向量数据库（RAG 功能需要）

```bash
docker run -d -p 8000:8000 chromadb/chroma
```

### 6. Docker 部署

```bash
# Node.js 版
cp server/.env.example .env
docker-compose up -d

# Python 版
cp server-py/.env.example .env
docker-compose -f docker-compose-python.yml up -d
```

## 项目结构

```
workmind7/
├── frontend/                Vue3 前端
│   ├── src/
│   │   ├── views/           各模块页面
│   │   ├── components/      UI 组件
│   │   ├── stores/          Pinia 状态
│   │   ├── composables/     组合式函数
│   │   ├── utils/           工具（http、sse）
│   │   └── styles/          全局样式
│   └── vite.config.js
│
├── server/                  Node.js 后端
│   ├── src/
│   │   ├── routes/          API 路由
│   │   ├── services/        业务逻辑
│   │   ├── middleware/       中间件
│   │   ├── utils/           工具（日志、错误）
│   │   └── config/          配置管理
│   └── Dockerfile
│
├── server-py/               Python 后端（FastAPI）
│   ├── app/
│   │   ├── routes/          API 路由（8 个模块，31 个接口）
│   │   ├── services/        业务逻辑
│   │   │   ├── chat/        对话记忆 + 用户画像
│   │   │   ├── agent/       ReAct Agent + 工具
│   │   │   ├── rag/         文档入库 + RAG 检索
│   │   │   ├── erp/         表单解析 + 审批流
│   │   │   ├── prompt/      模板 CRUD + A/B 评分
│   │   │   └── workflow/    LangGraph 工作流
│   │   ├── middleware/       中间件（限流、校验、安全）
│   │   ├── utils/           日志、错误处理
│   │   ├── config.py        配置管理
│   │   └── main.py          FastAPI 入口
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── docker-compose.yml             Node.js 版部署
├── docker-compose-python.yml      Python 版部署
└── README.md
```

## API 接口（31 个）

| 模块 | 接口数 | 说明 |
|------|--------|------|
| 对话 (`/api/chat`) | 5 | 流式对话、会话管理、用户画像、角色 |
| 知识库 (`/api/knowledge`) | 5 | 文档上传/列表/删除、RAG 问答、分类 |
| Agent (`/api/agent`) | 3 | Agent 执行（SSE）、工具列表、示例 |
| 工作流 (`/api/workflow`) | 3 | 模板列表、启动/恢复工作流（SSE） |
| ERP (`/api/erp`) | 5 | 表单解析、审批流（SSE）、申请管理 |
| Prompt (`/api/prompt`) | 8 | 测试（SSE）、A/B 对比、模板 CRUD |
| 监控 (`/api/monitor`) | 2 | 统计看板、预算设置 |
| 健康检查 (`/health`) | 2 | 存活检查、健康详情 |
