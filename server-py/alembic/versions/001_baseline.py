"""baseline revision

Revision ID: 001_baseline
Revises:
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True, comment="用户唯一标识"),
        sa.Column("username", sa.String(64), nullable=False, unique=True, comment="登录用户名"),
        sa.Column("password_hash", sa.String(256), nullable=False, comment="bcrypt 密码哈希"),
        sa.Column("role", sa.String(20), server_default="user", comment="角色"),
        sa.Column("created_at", sa.DateTime(), nullable=True, comment="创建时间"),
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True, comment="配置键"),
        sa.Column("value", postgresql.JSONB(), server_default="{}", comment="配置值"),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="更新时间"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("file_name", sa.String(256), nullable=False),
        sa.Column("category", sa.String(64), server_default="通用"),
        sa.Column("chunks", sa.Integer(), server_default="0"),
        sa.Column("chars", sa.Integer(), server_default="0"),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_rag_chunks_doc_id", "rag_chunks", ["doc_id"])

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_conversations_session", "conversations", ["session_id", "created_at"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "approval_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("form_type", sa.String(32), nullable=False),
        sa.Column("form_data", postgresql.JSONB(), nullable=False),
        sa.Column("flow_json", postgresql.JSONB(), nullable=False),
        sa.Column("approvers", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("final_comment", sa.Text(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "agent_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("config_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "monitor_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0"),
        sa.Column("output_tokens", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Float(), server_default="0"),
        sa.Column("cost_cny", sa.Float(), server_default="0"),
        sa.Column("latency_ms", sa.Float(), server_default="0"),
        sa.Column("from_cache", sa.Boolean(), server_default="false"),
        sa.Column("error", sa.Boolean(), server_default="false"),
    )


def downgrade() -> None:
    op.drop_table("monitor_records")
    op.drop_table("agent_configs")
    op.drop_table("approval_records")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("idx_conversations_session", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("idx_rag_chunks_doc_id", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_table("documents")
    op.drop_table("system_settings")
    op.drop_table("users")
