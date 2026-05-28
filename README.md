# WorkMind AI — 智能办公 Agent 平台

基于 Vue3 + FastAPI + LangChain + DeepSeek 构建的智能办公 Agent 系统。

## 项目模块

| 模块 | 说明 |
|------|------|
| 智能对话助手 | 多轮对话 / 流式输出 / 用户画像 |
| 知识库问答 | 文档上传 / RAG 检索 / 来源标注 |
| 任务 Agent | Function Call / ReAct / 工具可视化 |
| 内容工作流 | 周报/纪要/邮件/PRD 工作流（LangGraph） |
| ERP 报销请假 | 智能填单 / Multi-Agent 审批流 |
| Prompt 调试 | A/B 测试 / 版本管理 |
| 用量看板 | Token 消耗 / 费用 / 缓存统计 |

## 技术栈

- **前端**：Vue3 + Vite + Pinia + Vue Router + Element Plus
- **后端**：FastAPI + LangChain + LangGraph
- **模型**：DeepSeek
- **向量库**：Chroma

## 快速启动

### 1. 克隆项目

```powershell
git clone <repo-url>
cd workmind7
```

### 2. 配置环境变量

```powershell
cd server-py
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 启动后端

```powershell
cd server-py

# 安装依赖（uv 自动管理虚拟环境）
uv pip install -r requirements.txt

# 启动服务（使用项目虚拟环境中的 Python，避免全局 app 包冲突）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
# 服务启动在 http://localhost:3000
# API 文档：http://localhost:3000/docs
```

### 4. 启动前端

```powershell
cd frontend
pnpm install
pnpm dev
# 页面打开在 http://localhost:5173
```

### 5. 启动向量数据库（RAG 功能需要）

```powershell
docker run -d -p 8000:8000 chromadb/chroma
```

## 项目结构

```
workmind7/
├── frontend/                Vue3 前端
│   ├── src/
│   │   ├── views/           各模块页面
│   │   ├── components/      UI 组件
│   │   ├── stores/          Pinia 状态管理
│   │   ├── utils/           工具（http）
│   │   └── styles/          全局样式
│   ├── package.json
│   └── vite.config.js
│
├── server-py/               Python 后端（FastAPI）
│   ├── app/
│   │   ├── routes/          API 路由（8 个模块）
│   │   ├── services/        业务逻辑
│   │   │   ├── chat/        对话 + 记忆
│   │   │   ├── agent/       ReAgent Agent + 工具
│   │   │   ├── rag/         文档入库 + RAG 检索
│   │   │   ├── erp/         表单解析 + 审批流
│   │   │   ├── prompt/      模板 CRUD + A/B 评分
│   │   │   └── workflow/    LangGraph 工作流
│   │   ├── middleware/      中间件（限流、校验、安全）
│   │   ├── utils/           日志、错误处理
│   │   ├── config.py        配置管理
│   │   └── main.py          FastAPI 入口
│   ├── requirements.txt
│   └── .env.example
│
└── README.md
```

## API 接口

| 模块 | 路由前缀 | 说明 |
|------|---------|------|
| 对话 | `/api/chat` | 流式对话、会话管理、用户画像、角色 |
| 知识库 | `/api/knowledge` | 文档上传/列表/删除、RAG 问答、分类 |
| Agent | `/api/agent` | Agent 执行（SSE）、工具列表、示例 |
| 工作流 | `/api/workflow` | 模板列表、启动/恢复工作流（SSE） |
| ERP | `/api/erp` | 表单解析、审批流（SSE）、申请管理 |
| Prompt | `/api/prompt` | 测试（SSE）、A/B 对比、模板 CRUD |
| 监控 | `/api/monitor` | 统计看板、预算设置 |
| 健康检查 | `/health` | 存活检查、健康详情 |
