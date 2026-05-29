-- PGVector 统一存储 - 表结构初始化脚本
-- 运行方式: psql -U ai_love -d ai_love_vector -f init_pgvector.sql
-- 或者在 Python 中调用 init_db()

-- ── 启用 pgvector 扩展 ─────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 1. RAG 知识库切片表 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT,  -- 存储为字符串，格式 '[0.1, 0.2, ...]'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 向量索引（IVFFlat 算法，适合百万级数据）
CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks(doc_id);

-- 使用 pgvector 的向量索引（cosine distance）
-- 注意：embedding 列需要是 vector 类型才能创建向量索引
-- 如果 embedding 是 TEXT，注释掉下面这一行
-- CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding ON rag_chunks USING ivfflat (embedding vector_cosine_ops);

-- 如果上面报错（embedding 是 TEXT），执行 ALTER TABLE 转换：
-- ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE TEXT;

-- ── 2. 对话历史表 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(128) NOT NULL,
    role VARCHAR(20) NOT NULL,  -- user/assistant/system
    content TEXT NOT NULL,
    model VARCHAR(64),
    tokens INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id, created_at);

-- ── 3. 审批记录表 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approval_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(128),
    form_type VARCHAR(32) NOT NULL,  -- expense/leave
    form_data JSONB NOT NULL,
    flow_json JSONB NOT NULL,
    approvers JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,  -- pending/approved/rejected
    final_comment TEXT,
    result_json JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approval_session ON approval_records(session_id);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_records(status);

-- ── 4. Agent/工作流配置表 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_type VARCHAR(32) NOT NULL,  -- agent/workflow/prompt/profile
    name VARCHAR(128) NOT NULL UNIQUE,
    config_json JSONB NOT NULL,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_configs_type ON agent_configs(config_type);
CREATE INDEX IF NOT EXISTS idx_agent_configs_active ON agent_configs(is_active);

-- ── 查看表结构 ─────────────────────────────────────────────
-- \d rag_chunks
-- \d conversations
-- \d approval_records
-- \d agent_configs