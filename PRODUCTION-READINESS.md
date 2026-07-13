# WorkMind AI — 生产就绪路线图

> 基于全栈审查结论整理的**可执行整改计划**。  
> 目标：从「内部演示 / POC」升级为「可内网试点生产」。

**最后更新**：2026-07-13  
**适用版本**：workmind7 `main` 分支当前快照

---

## 如何使用本文档

1. 按阶段顺序推进：**W0a → W0b → W1 → W2**（W1 内部分任务可并行）。
2. 每项任务完成后，勾选 **DoD（验收标准）** 全部通过再进入下一项。
3. PR 合并前对照 **PR 检查清单**（文末）。
4. 多人协作时参考 **并行轨道** 分工，避免互相阻塞。

### 阶段总览

| 阶段 | 周期（1 人） | 周期（2 人并行） | 目标 |
|------|-------------|-----------------|------|
| **W0a 热修** | 2–3 天 | 1–2 天 | 修复已知 Bug + 堵住最显眼的安全洞 |
| **W0b 安全基线** | 1–2 周 | 1 周 | 认证授权、费用控制、中间件加固 |
| **W1 工程化** | 1 周 | 3–5 天 | CI、类型校验、性能解阻塞、迁移基线 |
| **W2 生产就绪** | 1 周 | 3–5 天 | 容器化、分布式限流、前端测试、可观测性 |

**预计总工期**：单人 3–4 周；双人并行 2–2.5 周。

---

## W0a · 热修（2–3 天）

> 不依赖架构变更，可立即合并、立即验证。

### W0a-1 修复 Agent 回答未持久化

**问题**：`routes/agent.py` 中 `run_task()` 内 `full_answer = ''` 遮蔽外层 list，assistant 消息永不写入 DB。

**改动文件**：
- `server-py/app/routes/agent.py`

**DoD**：
- [ ] 运行 Agent 任务完成后，刷新页面 assistant 消息仍存在
- [ ] `GET /api/agent/history/{session_id}` 返回完整 user + assistant 记录
- [ ] 新增/更新回归测试覆盖该路径

---

### W0a-2 修复会话删除无效

**问题**：`routes/chat.py` 调用 `clear_history()` 未 `await`。

**改动文件**：
- `server-py/app/routes/chat.py`
- `server-py/app/services/chat/memory.py`（确认 `clear_history` 为 async）

**DoD**：
- [ ] `DELETE /api/chat/sessions/{id}` 后该 session 从列表消失
- [ ] 数据库 `conversations` 表中对应记录已删除
- [ ] 新增 API 测试：`test_should_delete_session_when_valid_id`

---

### W0a-3 DOMPurify 净化所有 v-html 路径

**问题**：`marked` 输出未经消毒直接 `v-html`，存在 XSS。

**改动文件**（统一抽 `frontend/src/utils/markdown.js`）：
- `frontend/src/components/chat/MessageBubble.vue`
- `frontend/src/components/rag/RagChat.vue`
- `frontend/src/views/AgentView.vue`
- `frontend/src/views/WorkflowView.vue`
- `frontend/src/views/PromptView.vue`
- `frontend/src/components/agent/ToolCallCard.vue`

**实施步骤**：
```bash
cd frontend
npm install dompurify
```

```javascript
// frontend/src/utils/markdown.js（建议新建）
import { marked } from 'marked'
import DOMPurify from 'dompurify'

export function renderMarkdown(content) {
  if (!content) return ''
  const raw = marked.parse(content)
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
}
```

**DoD**：
- [ ] 6 个文件全部改用 `renderMarkdown()`，无散落 `marked()` + `v-html` 组合
- [ ] 手动验证：输入 `<script>alert(1)</script>` 在聊天/RAG/Agent 界面均被净化
- [ ] `marked.setOptions` 只在一处配置（`markdown.js`）

---

### W0a-4 移除硬编码凭据默认值

**问题**：`config.py` 含真实格式 DB/Redis 密码默认值。

**改动文件**：
- `server-py/app/config.py`
- `server-py/app/core/database.py`（如有重复默认值）
- `server-py/.env.example`（确保与 compose 一致）

**DoD**：
- [ ] `DATABASE_URL`、`REDIS_PASSWORD` 无默认值；缺失时启动明确报错
- [ ] `.env.example` 与 `docker-compose.yml` 凭据一致（`workmind:workmind_dev`）
- [ ] `grep -r "zx4221335\|NFTurbo666\|ai_love" server-py/` 无命中

---

### W0a-5 剥离客户端堆栈泄露 + 关闭公开文档

**改动文件**：
- `server-py/app/services/agent/agent.py`（SSE error 事件移除 `traceback` 字段）
- `server-py/app/main.py`（生产环境 `docs_url=None`, `redoc_url=None`）

**DoD**：
- [ ] Agent 错误 SSE 事件仅含用户友好 `message`，无内部路径
- [ ] `NODE_ENV=production` 时 `/docs`、`/redoc` 返回 404
- [ ] 开发环境 `/docs` 仍可访问

---

### W0a-6 清理测试凭据

**改动文件**：
- `server-py/tests/conftest.py`

**DoD**：
- [ ] 测试 DB URL 使用占位符：`postgresql+asyncpg://test:test@localhost:5434/workmind_test`
- [ ] 凭据通过 `TEST_DATABASE_URL` 环境变量注入，文档写在 `server-py/tests/README.md` 或 conftest 注释

---

### W0a 阶段门禁

全部 6 项 DoD 勾选后，方可进入 W0b。

```bash
# W0a 快速验证命令
cd server-py && uv run pytest tests/integration/test_sse_streaming.py -q
cd frontend && npm run build
```

---

## W0b · 安全基线（1–2 周）

> 架构级变更，需前后端联调。

### W0b-1 认证体系（JWT 或 API Key）

**推荐方案（内网试点）**：JWT Bearer Token + 角色（`user` / `admin`）。

**改动文件**：
- `server-py/app/middleware.py` 或新建 `app/auth/`
- `server-py/app/config.py`（`JWT_SECRET`, `JWT_EXPIRE_HOURS`）
- `server-py/.env.example`
- `frontend/src/utils/http.js`（axios + fetchStream 注入 `Authorization`）
- 所有 `routes/*.py`（敏感路由加 `Depends(get_current_user)`）

**DoD**：
- [ ] 无 token 访问任意 `/api/*`（除 `/health/*`）返回 401
- [ ] 有效 token 可正常调用 chat/knowledge
- [ ] token 过期返回 401，前端跳转登录或提示重新认证
- [ ] `JWT_SECRET` 仅从环境变量读取，启动时校验非空

---

### W0b-2 路由权限矩阵

| 路由前缀 | 最低角色 | 说明 |
|----------|---------|------|
| `/api/chat/*` | `user` | 仅访问本人 `userId` 数据 |
| `/api/knowledge/*` | `user` | 上传/删除需 `user`；查询可读 |
| `/api/agent/*` | `user` | 同上 |
| `/api/workflow/*` | `user` | 同上 |
| `/api/erp/*` | `user` | 同上 |
| `/api/prompt/*` | `admin` | Prompt 调试台 |
| `/api/configs/*` | `admin` | 系统配置 |
| `/api/monitor/*` | `admin` | 监控与预算 |
| `/health/*` | 无 | 存活探针 |

**DoD**：
- [ ] `user` 角色访问 `/api/configs` 返回 403
- [ ] `user` A 无法读取 `user` B 的 session（IDOR 修复）
- [ ] 权限矩阵写入本文档或 `docs/permissions.md` 并保持同步

---

### W0b-3 预算超支硬拦截

**改动文件**：
- `server-py/app/services/interceptor.py` 或新建 `app/services/budget_guard.py`
- `server-py/app/routes/monitor.py`

**DoD**：
- [ ] 月度费用达预算 100% 时，LLM 调用返回 429 或 402，附明确错误码 `BUDGET_EXCEEDED`
- [ ] 管理员可通过 `/api/monitor/budget` 调整上限
- [ ] 拦截逻辑在认证之后、LLM 调用之前执行

---

### W0b-4 Redis 加固

**改动文件**：
- `docker-compose.yml`（`requirepass`、不对外暴露端口或仅 bind localhost）
- `server-py/app/core/redis_client.py`
- `server-py/.env.example`

**DoD**：
- [ ] Redis 启用密码；无密码时开发环境启动告警
- [ ] 生产 compose 中 Redis 端口不映射到 `0.0.0.0`（或仅内网）
- [ ] 应用连接失败时 `/health/ready` 返回 503

---

### W0b-5 CORS 收紧

**改动文件**：
- `server-py/app/middleware.py`
- `server-py/.env.example`（`ALLOWED_ORIGINS` 示例）

**DoD**：
- [ ] 生产环境 `ALLOWED_ORIGINS` 为显式域名列表，禁止 `*`
- [ ] `allow_methods` 限制为 `GET, POST, PUT, DELETE, OPTIONS`
- [ ] `allow_headers` 限制为 `Content-Type, Authorization, X-Trace-Id`

---

### W0b 阶段门禁

```bash
# 无 token 应 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/api/chat/sessions
# 期望: 401

# admin 路由非 admin 应 403
curl -s -H "Authorization: Bearer <user-token>" http://localhost:3001/api/configs
# 期望: 403
```

---

## W1 · 工程化（1 周，部分可并行）

### W1-1 健康检查分离

**改动文件**：
- `server-py/app/routes/health.py`
- `server-py/app/core/database.py`（移除 health 路径中的自动建表副作用）

**DoD**：
- [ ] `GET /health/live` → 200（进程存活，不查依赖）
- [ ] `GET /health/ready` → DB + Redis 均可用时 200，否则 503
- [ ] health 检查**不**执行 `CREATE TABLE`

---

### W1-2 关键回归测试（CI 前置）

**新增测试**（在开 CI 之前完成）：
- `tests/integration/test_chat_sessions.py` — 删除会话
- `tests/integration/test_agent_persistence.py` — Agent 消息持久化
- `tests/integration/test_auth.py` — 401/403 矩阵

**DoD**：
- [ ] 上述 3 个测试文件存在且本地通过
- [ ] 全部使用 mock LLM（`deepseek-chat`），不调真实 API

---

### W1-3 CI 流水线

**新建文件**：`.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: workmind_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv pip install -r server-py/requirements.txt ruff mypy pytest pytest-asyncio httpx
      - run: cd server-py && ruff check .
      - run: cd server-py && ruff format --check .
      - env:
          DEEPSEEK_API_KEY: sk-test-mock
          DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/workmind_test
        run: cd server-py && pytest -m "not live and not slow" -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: cd frontend && npm ci && npm run build
```

**DoD**：
- [ ] PR 上 backend + frontend job 均必须通过才能合并
- [ ] `live` / `slow` 标记测试默认不跑
- [ ] CI 失败时 GitHub 显示明确错误日志

---

### W1-4 Pydantic 替换 `req: dict`

**优先改造路由**（按风险排序）：
1. `routes/config.py`
2. `routes/monitor.py`
3. `routes/knowledge.py`
4. `routes/erp.py`
5. `routes/prompt.py`
6. `routes/workflow.py`

**DoD**：
- [ ] 上述路由无 `req: dict` 裸参数
- [ ] OpenAPI `/docs` 中请求体 schema 准确
- [ ] 超长字段有 `Field(max_length=...)`

---

### W1-5 异步路径解阻塞

**改动文件**：
- `server-py/app/services/model.py` — `asyncio.to_thread(encode, ...)`
- `server-py/app/services/rag/query.py` — `to_thread(reranker.rerank, ...)`
- `server-py/app/routes/knowledge.py` — 上传写文件用 `aiofiles` 或 `to_thread`

**DoD**：
- [ ] 10 并发 embedding 请求，事件循环无明显阻塞（可用 `asyncio` 延迟任务对比）
- [ ] 无新增同步 Redis 调用进入 async 路由热路径

---

### W1-6 SSE AbortController

**改动文件**：
- `frontend/src/utils/http.js`
- `frontend/src/stores/chat.js`, `agent.js`, `knowledge.js`, `workflow.js`
- `frontend/src/components/chat/ChatInput.vue`

**DoD**：
- [ ] 点击「停止」后 SSE 连接断开，后端任务在合理时间内取消
- [ ] 重复发送不会叠加多个并发流

---

### W1-7 Alembic 迁移基线

**改动文件**：
- 新建 `server-py/alembic/` 目录与 `alembic.ini`
- `server-py/scripts/init_db.py` 标记为开发专用

**DoD**：
- [ ] `alembic upgrade head` 可从零创建全部表
- [ ] 生产启动不再调用 `init_db()` 自动建表
- [ ] 首次 baseline revision 与当前 `entities.py` 一致

---

## W2 · 生产就绪（1 周）

### W2-1 Dockerfile + 全栈 Compose

**新建文件**：
- `server-py/Dockerfile`
- `docker-compose.prod.yml`（app + postgres + redis）

**DoD**：
- [ ] `docker compose -f docker-compose.prod.yml up` 可启动完整栈
- [ ] 镜像不含 `.env`、不含开发凭据
- [ ] uvicorn 使用 `--workers 1`（限流改 Redis 前）或文档说明多 worker 限流行为

---

### W2-2 Redis 分布式限流

**改动文件**：
- `server-py/app/middleware.py` — 替换进程内 `TokenBucket`
- 可选依赖：`slowapi` 或自研 Redis 滑动窗口

**DoD**：
- [ ] 限流按 IP（匿名）或 userId（已认证）维度
- [ ] 多 worker / 多实例下限流阈值一致
- [ ] LLM 昂贵接口（`/api/agent/run`）限流严于 `/health/live`

---

### W2-3 前端核心路径测试

```bash
cd frontend
npm install -D vitest @vue/test-utils jsdom
```

**优先覆盖**：
- `utils/markdown.js` — XSS 净化
- `utils/http.js` — token 注入、SSE 解析
- `components/chat/MessageBubble.vue` — 渲染

**DoD**：
- [ ] `npm run test` 在 CI frontend job 中执行
- [ ] `package.json` 增加 `"test": "vitest run"`

---

### W2-4 前端 Lint + 锁文件统一

**DoD**：
- [ ] 删除 `frontend/pnpm-lock.yaml` 或 `package-lock.json` 之一（统一 npm）
- [ ] 添加 ESLint + `npm run lint` 脚本
- [ ] CI frontend job 增加 `npm run lint`

---

### W2-5 可观测性与优雅关闭

**改动文件**：
- `server-py/app/main.py` — lifespan 中调用 `close_db()`, `close_redis()`
- `server-py/app/middleware.py` — `print` 改为 `logger`
- 可选：Sentry / Langfuse 接入

**DoD**：
- [ ] SIGTERM 后进程在 30s 内退出，DB/Redis 连接池已释放
- [ ] 请求日志含 `trace_id`，无密码/API Key 明文
- [ ] `asyncio.create_task` 后台任务在 shutdown 时被 cancel

---

### W2-6 前端 Bundle 优化（可选，不阻断上线）

- ECharts 按需引入
- Element Plus Icons 按需注册
- Vite `manualChunks` 拆分 vendor

**DoD**：
- [ ] 生产 build 首屏 JS < 500KB gzip（基线记录到本文档）

---

## 并行轨道（多人协作）

```
时间 →
轨道 A（后端）:  W0a Bug修复 → W0b 认证 → W1 Pydantic → W1 Alembic → W2 限流
轨道 B（前端）:  W0a DOMPurify → W0b token注入 → W1 AbortController → W2 Vitest
轨道 C（DevOps）: W0a 凭据清理 → W0b Redis/CORS → W1 CI → W2 Dockerfile
轨道 D（测试）:   W0a 回归用例 → W1 auth测试 → W2 评测CI门禁
```

**汇合点**：W0b-1 认证完成后，轨道 B 才能联调；W1-2 测试完成后，轨道 C 才能开 CI。

---

## 回滚与灰度策略

| 变更 | 回滚方式 | 灰度建议 |
|------|---------|---------|
| JWT 认证 | Feature flag `AUTH_ENABLED=false` 绕过中间件 | 先对内网 IP 强制，外网观察 |
| Redis 密码 | compose 回滚 + 旧 env | 先 staging 验证连接串 |
| 预算拦截 | 环境变量 `BUDGET_ENFORCE=false` | 先告警不拦截，一周后强制 |
| Alembic | `alembic downgrade -1` | staging 先跑 migration |
| DOMPurify | 前端静态资源回滚 | 可直接全量，风险低 |

---

## PR 检查清单

每个 PR 合并前确认：

- [ ] 无硬编码凭据、API Key、真实密码
- [ ] 新增路由有认证 + 权限校验
- [ ] 新增 `v-html` 必须经过 `renderMarkdown()`
- [ ] 异步路由无新增同步阻塞 IO
- [ ] 有对应测试或说明为何不测
- [ ] `.env.example` 已同步更新
- [ ] `ruff check` + `pytest -m "not live"` 本地通过
- [ ] `npm run build` 本地通过

---

## 上线前最终门禁（Go / No-Go）

全部勾选方可内网试点生产：

### 安全
- [ ] W0a + W0b 全部 DoD 完成
- [ ] 渗透自查：无 token 不可调用 LLM / 上传文档 / 改配置
- [ ] XSS 手工验证通过

### 功能
- [ ] Agent / Chat 历史持久化正常
- [ ] 会话删除正常
- [ ] RAG 问答 + 来源引用正常

### 工程
- [ ] CI 绿色
- [ ] `/health/ready` 接入负载均衡
- [ ] Dockerfile 可构建、可启动
- [ ] 生产 `.env` 与 compose 凭据一致

### 运维
- [ ] 日志无敏感信息
- [ ] 预算拦截已启用或明确豁免并记录
- [ ] 回滚方案已文档化并演练一次

---

## 附录 A：已知问题索引

| ID | 严重度 | 问题 | 阶段 |
|----|--------|------|------|
| SEC-01 | P0 | 无认证 | W0b-1 |
| SEC-02 | P0 | 硬编码凭据 | W0a-4 |
| SEC-03 | P0 | XSS v-html | W0a-3 |
| SEC-04 | P0 | admin 接口开放 | W0b-2 |
| SEC-05 | P1 | CORS 过宽 | W0b-5 |
| SEC-06 | P1 | Redis 无密码 | W0b-4 |
| SEC-07 | P1 | OpenAPI 公开 | W0a-5 |
| BUG-01 | P0 | Agent 持久化 | W0a-1 |
| BUG-02 | P0 | 会话删除 | W0a-2 |
| PERF-01 | P1 | 同步 IO 阻塞 | W1-5 |
| PERF-02 | P1 | N+1 查询 | W2+ 专项 |
| PERF-03 | P2 | 前端 bundle 过大 | W2-6 |
| OPS-01 | P1 | 无 CI | W1-3 |
| OPS-02 | P1 | 无 Alembic | W1-7 |
| OPS-03 | P1 | 无 Dockerfile | W2-1 |

---

## 附录 B：环境变量清单（生产必填）

```ini
# 认证
JWT_SECRET=<随机 64 字符>
JWT_EXPIRE_HOURS=24

# 数据库
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/workmind

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=<强密码>

# LLM
DEEPSEEK_API_KEY=sk-...

# 应用
NODE_ENV=production
ALLOWED_ORIGINS=https://workmind.example.com
PORT=3001

# 可选
BUDGET_ENFORCE=true
AUTH_ENABLED=true
```

---

<p align="center">
  完成全部阶段后，将本文档顶部的「适用版本」更新为发布 tag，并归档至 <code>docs/releases/</code>。
</p>
