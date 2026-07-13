-- workmind7 PostgreSQL 首次初始化（仅空库执行一次）
-- 表结构由 server-py/scripts/init_db.py 创建，此处只启用 pgvector 扩展

CREATE EXTENSION IF NOT EXISTS vector;
