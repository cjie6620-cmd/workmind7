> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# DevOps 规范（uv + Docker Compose + GPU 部署 + LLM 中间件）

> 适用场景：Python + FastAPI + LLM 应用的部署、CI/CD、中间件编排、监控。
>
> 与 [backend-fastapi.md](backend-fastapi.md)（应用启动）/ [dba.md](dba.md)（数据库迁移）/ [agent.md](agent.md)（LLM 服务）协同。

---

## 脚本规则

### Bash 脚本规范

强制：
- **首行 shebang**：`#!/usr/bin/env bash`
- **set -e**：遇错即停
- **set -u**：未定义变量报错
- **set -o pipefail**：管道失败捕获
- **变量大写 + `${}`**：`${VAR_NAME}` 而非 `$VAR_NAME`
- **字符串引号**：双引号包裹含变量的字符串
- **日志函数**：用 `log_info` / `log_error` 统一格式
- **退出码**：非 0 退出 + `exit 1`

```bash
#!/usr/bin/env bash
set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 错误处理
trap 'log_error "Script failed on line $LINENO"' ERR

main() {
    log_info "Starting deployment..."
    # ...
    log_info "Done"
}

main "$@"
```

### Python 脚本规范

- 使用 `if __name__ == "__main__":` 入口
- 复杂脚本用 `argparse` / `typer`
- 错误用 `raise` + 自定义异常类
- 日志用 `loguru`

---

## uv 命令规范

### 日常开发

```bash
# 初始化（强制 uv，不用 pip / poetry / pdm）
uv init my-project
cd my-project

# 添加依赖
uv add fastapi 'uvicorn[standard]' sqlalchemy[asyncio] asyncpg
uv add --dev pytest ruff mypy

# 同步环境（替代 pip install -r requirements.txt）
uv sync

# 运行命令（自动激活 venv）
uv run pytest
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 删除依赖
uv remove requests

# 升级依赖
uv lock --upgrade
uv sync
```

### 依赖锁定

```bash
# 锁定依赖（生成 uv.lock，必须提交到 git）
uv lock

# 检查过期
uv lock --upgrade --dry-run
```

### pyproject.toml 标准结构

```toml
[project]
name = "{project-name}"
version = "0.1.0"
description = "{项目描述}"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",
    "loguru>=0.7.0",
    "httpx>=0.27.0",
    "langchain>=0.3.0",
    "langgraph>=0.2.0",
    "langfuse>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
    "factory-boy>=3.3.0",
    "faker>=26.0.0",
    "testcontainers[postgres]>=4.8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "PT", "RUF"]
ignore = ["E501"]

[tool.mypy]
strict = true
python_version = "3.12"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 容器内运行（强制）

```dockerfile
# 阶段 1：构建（用 uv）
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev

# 阶段 2：运行时（精简）
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
```

---

## Docker Compose 规范（LLM 应用专属中间件）

### 目录结构

```
deploy/
├── docker-compose.yml         # 主 compose
├── docker-compose.dev.yml     # 开发覆盖
├── .env.example
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   └── dashboards/
└── scripts/
    ├── ensure_running.sh      # 启动中间件
    ├── healthcheck.sh         # 健康检查
    └── reset.sh               # 重置（慎用）
```

### docker-compose.yml（核心中间件）

```yaml
version: '3.9'

services:
  # ============ 应用 ============
  app:
    build: ..
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      minio: { condition: service_healthy }
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: '2', memory: 4G }

  # ============ PostgreSQL + pgvector ============
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5

  # ============ Redis ============
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes: ["redisdata:/data"]
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  # ============ MinIO（对象存储） ============
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes: ["miniodata:/data"]
    ports: ["9000:9000", "9001:9001"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s

  # ============ Qdrant（向量库，生产选） ============
  qdrant:
    image: qdrant/qdrant:latest
    volumes: ["qdrantdata:/qdrant/storage"]
    ports: ["6333:6333", "6334:6334"]
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:6333/health"]
      interval: 10s

  # ============ Neo4j（图数据库，可选） ============
  neo4j:
    image: neo4j:5.20
    environment:
      NEO4J_AUTH: ${NEO4J_USER}/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc"]'
    volumes: ["neo4jdata:/data"]
    ports: ["7474:7474", "7687:7687"]

  # ============ vLLM（本地 LLM 推理，GPU，国产开源模型） ============
  vllm:
    image: vllm/vllm-openai:latest
    runtime: nvidia  # 启用 GPU
    environment:
      NVIDIA_VISIBLE_DEVICES: all
    command: >
      --model deepseek-ai/DeepSeek-V3-Base
      --tensor-parallel-size 1
      --max-model-len 32768
      --gpu-memory-utilization 0.85
      --trust-remote-code
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    ports: ["8001:8000"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/v1/models"]
      interval: 30s
      timeout: 10s
      retries: 10

  # ============ Langfuse（LLM 可观测） ============
  langfuse:
    image: langfuse/langfuse:latest
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_SECRET}
    ports: ["3000:3000"]
    depends_on:
      postgres: { condition: service_healthy }

  # ============ Prometheus（监控） ============
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
    ports: ["9090:9090"]

  # ============ Grafana（看板） ============
  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    volumes:
      - grafanadata:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
    ports: ["3001:3000"]
    depends_on: [prometheus]

volumes:
  pgdata: {}
  redisdata: {}
  miniodata: {}
  qdrantdata: {}
  neo4jdata: {}
  grafanadata: {}
```

### 容器密码说明

**强制**：
- 所有密码通过 `.env` 文件注入，**禁止**硬编码在 compose 中
- 开发环境使用弱密码 + 占位符（提交 `.env.example`）
- 生产环境使用 Secret Manager / K8s Secret / Vault
- `.env` 加入 `.gitignore`

`.env.example`：

```bash
POSTGRES_DB={db_name}
POSTGRES_USER=postgres
POSTGRES_PASSWORD=CHANGE_ME
REDIS_PASSWORD=CHANGE_ME
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=CHANGE_ME
NEO4J_USER=neo4j
NEO4J_PASSWORD=CHANGE_ME
LANGFUSE_SECRET=$(openssl rand -hex 32)
GRAFANA_PASSWORD=CHANGE_ME

# LLM（**强制国产模型，禁止任何国外 API**）
# 主力：DeepSeek（必填）
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
# 备选：通义千问 / 智谱 GLM（可选）
DASHSCOPE_API_KEY=sk-xxx
ZHIPUAI_API_KEY=xxx

# 可观测
LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx
```

### 启动与校验脚本

```bash
#!/usr/bin/env bash
# deploy/scripts/ensure_running.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

# 1. 检查 Docker
if ! docker info >/dev/null 2>&1; then
    echo "[INFO] Docker not running, attempting to start..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open -a Docker
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        powershell.exe -Command "Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'"
    fi
    sleep 10
fi

# 2. 检查端口冲突
check_port() {
    local port=$1
    if lsof -Pi :${port} -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "[WARN] Port ${port} is in use"
        return 1
    fi
}

for p in 5432 6379 9000 6333 8000; do
    check_port $p || true
done

# 3. 拉起服务
docker compose up -d

# 4. 健康检查
echo "[INFO] Waiting for services..."
sleep 15
./scripts/healthcheck.sh
```

```bash
#!/usr/bin/env bash
# deploy/scripts/healthcheck.sh
set -euo pipefail

check_service() {
    local name=$1
    local url=$2
    if curl -sf -m 5 "$url" >/dev/null 2>&1; then
        echo "  ✅ ${name} OK"
    else
        echo "  ❌ ${name} FAILED"
        return 1
    fi
}

echo "=== Service Health ==="
check_service "PostgreSQL" "http://localhost:5432" || true
check_service "Redis" "http://localhost:6379" || true
check_service "MinIO" "http://localhost:9000/minio/health/live"
check_service "Qdrant" "http://localhost:6333/health"
check_service "App" "http://localhost:8000/health"
check_service "Langfuse" "http://localhost:3000"
```

---

## FastAPI 应用部署规范

### 开发环境启动

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 生产环境启动

```bash
# 多 worker（推荐：worker 数 = (CPU 核数 × 2) + 1）
uv run gunicorn app.main:app \
    -w 4 \
    -k uvicorn.workers.UvicornWorker \
    -b 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
```

### 健康检查端点（必备）

```python
# app/main.py
from fastapi import FastAPI, status
from sqlalchemy import text
from app.core.db import async_session_factory
from app.core.cache import redis_client

app = FastAPI()

@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    """Liveness probe - 进程是否存活"""
    return {"status": "ok"}

@app.get("/ready", status_code=status.HTTP_200_OK)
async def readiness():
    """Readiness probe - 依赖是否就绪"""
    checks = {}

    # DB
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"failed: {e}"

    # Redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"failed: {e}"

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
```

### .gitignore 标准内容

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# 项目
.env
.env.local
*.log
logs/
data/
.DS_Store

# IDE
.vscode/
.idea/

# Docker
deploy/data/
deploy/*.env
```

---

## CI/CD 流水线（GitHub Actions 示例）

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready" --health-interval 5s
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v3
        with:
          version: "latest"

      - name: Install dependencies
        run: uv sync --frozen

      - name: Lint
        run: |
          uv run ruff check .
          uv run ruff format --check .
          uv run mypy app/

      - name: Test
        env:
          DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379/0
        run: |
          uv run pytest --cov=app --cov-report=xml

      - name: RAG Eval
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: |
          uv run pytest tests/eval/ --dataset=eval_dataset/rag_v1

  build:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
```

---

## 监控告警（Prometheus + Grafana）

### 应用埋点

```python
# app/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# LLM 调用计数
LLM_CALL_TOTAL = Counter(
    "llm_call_total",
    "Total LLM API calls",
    ["model", "status"],  # status: success/error
)

# LLM 延迟
LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM call latency",
    ["model"],
    buckets=[0.1, 0.5, 1, 2, 5, 10],
)

# Token 使用量
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "type"],  # type: input/output
)

# RAG 检索延迟
RAG_RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_seconds",
    "RAG retrieval latency",
    ["retriever_type"],  # vector/bm25/hybrid
)
```

### prometheus.yml

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'fastapi-app'
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics
```

### Grafana 看板（必备）

| 看板 | 指标 |
|------|------|
| **LLM 成本** | 5min / 1h / 1d 总成本、按模型拆分、按用户 Top10 |
| **LLM 延迟** | P50 / P95 / P99 TTFT / TPOT |
| **LLM 错误率** | 4xx / 5xx / 超时 占比 |
| **RAG 召回** | top-1 命中率、平均召回数、检索延迟 |
| **GPU 监控** | 显存使用率、GPU 利用率、推理吞吐 |
| **应用健康** | QPS、错误率、P95 响应时间 |

---

## 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f app
docker compose logs -f --tail 100 vllm

# 进入容器
docker compose exec app bash
docker compose exec postgres psql -U postgres -d {db_name}

# 重启单个服务
docker compose restart app

# 扩缩容
docker compose up -d --scale app=3

# 数据库迁移
docker compose exec app uv run alembic upgrade head

# 备份数据库
docker compose exec postgres pg_dump -U postgres {db_name} > backup_$(date +%Y%m%d).sql

# 恢复
cat backup_xxx.sql | docker compose exec -T postgres psql -U postgres -d {db_name}

# 清理
docker system prune -a
docker volume prune  # 慎用，删除所有卷
```

---

## 禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **包管理** | ❌ pip / poetry / pdm（用 uv）；❌ requirements.txt 与 pyproject.toml 并存 |
| **脚本** | ❌ 无 shebang；❌ 不用 `set -e`；❌ 字符串拼命令；❌ 密码明文写脚本 |
| **Docker** | ❌ 镜像用 `latest` 标签（锁版本）；❌ 应用进程以 root 运行；❌ docker-compose 内含应用代码（用 build） |
| **Compose** | ❌ 密码硬编码在 compose；❌ .env 提交到 git；❌ 端口冲突不检查 |
| **生产** | ❌ 裸 uvicorn 跑生产（用 gunicorn）；❌ 单 worker；❌ 无健康检查；❌ 无资源限制 |
| **监控** | ❌ 不埋点；❌ 关键指标无告警；❌ 日志无结构化 |
| **GPU** | ❌ 不用 `runtime: nvidia`；❌ 模型权重提交到 git（挂载 volume）；❌ 显存不限制；❌ **部署 Llama / Mistral 等国外开源模型（用 DeepSeek / Qwen / GLM 等国产开源模型）** |
| **CI/CD** | ❌ 测试中调真实 LLM API；❌ 不跑 lint/test 直接合并；❌ 镜像不打 tag；❌ **CI 中使用 OPENAI_API_KEY / ANTHROPIC_API_KEY 等国外 Key** |
| **运维** | ❌ `docker system prune -a --volumes`（生产慎用）；❌ 直接 `DROP DATABASE`；❌ 不备份就升级 |
| **模型合规** | ❌ 在 .env / Secrets 中配置 OPENAI_API_KEY / ANTHROPIC_API_KEY；❌ vLLM 部署 Llama / Mixtral 等国外模型；❌ 引入 `openai` / `anthropic` SDK 作为生产依赖 |
