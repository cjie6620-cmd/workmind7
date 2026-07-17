-- PostgreSQL 容器首次初始化只负责数据库扩展。
--
-- 业务表结构的唯一来源是 server-py/alembic/versions；应用容器启动时
-- docker-entrypoint.sh 会执行 `alembic upgrade head`。不要在此复制建表 SQL
-- 或手工写 alembic_version，否则 fresh install 与升级库会产生 schema 漂移。

CREATE EXTENSION IF NOT EXISTS vector;
