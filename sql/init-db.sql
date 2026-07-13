-- workmind7 PostgreSQL 全量初始化脚本（与 alembic 001_baseline 对齐）
-- 适用场景：Docker 空库首次启动、手工 psql 初始化
--
-- Docker（空数据卷时自动执行）:
--   docker compose -f docker/docker-compose.yml up -d postgres
--
-- 手工执行:
--   psql -U workmind -d workmind_vector -f sql/init-db.sql
--
-- 说明：若已用本脚本建表，Alembic 可执行 `alembic stamp 001_baseline` 标记版本，无需再 upgrade。

-- ── 扩展 ──────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 1. 用户表 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          VARCHAR(64)  PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    role        VARCHAR(20)  NOT NULL DEFAULT 'user',
    created_at  TIMESTAMP
);

-- ── 2. 系统配置表 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_settings (
    key         VARCHAR(64) PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP
);

-- ── 3. 知识库文档元信息 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          VARCHAR(64)  PRIMARY KEY,
    title       VARCHAR(256) NOT NULL,
    file_name   VARCHAR(256) NOT NULL,
    category    VARCHAR(64)  NOT NULL DEFAULT '通用',
    chunks      INTEGER      NOT NULL DEFAULT 0,
    chars       INTEGER      NOT NULL DEFAULT 0,
    preview     TEXT,
    created_at  TIMESTAMP
);

-- ── 4. RAG 知识库切片（pgvector 1024 维，bge-m3）──────────
CREATE TABLE IF NOT EXISTS rag_chunks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id       UUID NOT NULL,
    chunk_index  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector(1024),
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks (doc_id);

-- ── 5. 对话历史 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  VARCHAR(128) NOT NULL,
    user_id     VARCHAR(64),
    role        VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    model       VARCHAR(64),
    tokens      INTEGER,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations (session_id, created_at);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

-- ── 6. 审批记录 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approval_records (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     VARCHAR(128),
    form_type      VARCHAR(32) NOT NULL,
    form_data      JSONB NOT NULL,
    flow_json      JSONB NOT NULL,
    approvers      JSONB NOT NULL,
    status         VARCHAR(32) NOT NULL,
    final_comment  TEXT,
    result_json    JSONB,
    created_at     TIMESTAMP,
    completed_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approval_session ON approval_records (session_id);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_records (status);

-- ── 7. Agent / 工作流 / Prompt 配置 ───────────────────────
CREATE TABLE IF NOT EXISTS agent_configs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_type  VARCHAR(32) NOT NULL,
    name         VARCHAR(128) NOT NULL UNIQUE,
    config_json  JSONB NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_configs_type ON agent_configs (config_type);
CREATE INDEX IF NOT EXISTS idx_agent_configs_active ON agent_configs (is_active);

-- ── 8. LLM 用量监控 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_records (
    id            SERIAL PRIMARY KEY,
    time          TIMESTAMP NOT NULL,
    feature       VARCHAR(32) NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_cny      DOUBLE PRECISION NOT NULL DEFAULT 0,
    latency_ms    DOUBLE PRECISION NOT NULL DEFAULT 0,
    from_cache    BOOLEAN NOT NULL DEFAULT FALSE,
    error         BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_monitor_records_time ON monitor_records (time);
CREATE INDEX IF NOT EXISTS idx_monitor_records_feature ON monitor_records (feature);

-- ── Alembic 版本标记（与 001_baseline 一致）──────────────
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

INSERT INTO alembic_version (version_num)
VALUES ('001_baseline')
ON CONFLICT (version_num) DO NOTHING;
