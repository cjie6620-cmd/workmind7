"""
SQLAlchemy ORM 模型定义

对应 PostgreSQL 表结构，使用 pgvector 存储向量
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from ..core.database import Base
from ..utils.business_time import utc_now_naive


class User(Base):
    """
    用户表

    存储登录账号与角色，密码为 bcrypt 哈希
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户唯一标识，与 JWT sub 一致")
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录用户名")
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False, comment="bcrypt 密码哈希")
    role: Mapped[str] = mapped_column(
        String(20),
        default="user",
        server_default=text("'user'"),
        nullable=False,
        comment="角色：user / admin",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
        comment="账号是否允许登录和刷新令牌",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="创建时间",
    )


class SystemSetting(Base):
    """
    系统配置表

    持久化预算上限等全局设置
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, comment="配置键")
    value: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
        comment="配置值 JSON",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="更新时间",
    )


class Document(Base):
    """
    文档表

    存储知识库文档元信息
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="通用", server_default=text("'通用'"), nullable=False)
    chunks: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.id", name="fk_documents_owner", ondelete="SET NULL"),
        nullable=True,
        comment="上传者；NULL 表示迁移前的共享文档",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )

    __table_args__ = (Index("idx_documents_owner_created", "owner_user_id", "created_at"),)


class RagChunk(Base):
    """
    RAG 知识库切片表

    存储文档切片和对应的向量嵌入
    """

    __tablename__ = "rag_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", name="fk_rag_chunks_document", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # pgvector 向量类型（bge-m3 输出维度 1024）
    embedding = mapped_column(Vector(1024), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_rag_chunks_doc_id", "doc_id"),
        Index(
            "idx_rag_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
        UniqueConstraint("doc_id", "chunk_index", name="uq_rag_chunks_doc_chunk"),
    )


class Conversation(Base):
    """
    对话历史表

    存储用户与 AI 的对话记录
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True, comment="所属用户 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user/assistant/system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )

    __table_args__ = (Index("idx_conversations_session", "session_id", "created_at"),)


class ApprovalRecord(Base):
    """
    审批记录表

    存储审批流程的完整记录
    """

    __tablename__ = "approval_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="申请人用户 ID，由认证上下文写入")
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="客户端幂等请求 ID")
    form_type: Mapped[str] = mapped_column(String(32), nullable=False)  # expense/leave
    form_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    flow_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approvers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # pending/approved/rejected/needs_info/failed
    final_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_approval_session", "session_id", unique=True),
        Index("idx_approval_user_created", "user_id", "created_at"),
        Index(
            "uq_approval_user_request",
            "user_id",
            "request_id",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL"),
        ),
        Index("idx_approval_status", "status"),
    )


class AgentConfig(Base):
    """
    Agent/工作流配置表

    存储 Agent、工作流、Prompt 等配置
    """

    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_type: Mapped[str] = mapped_column(String(32), nullable=False)  # agent/workflow/prompt
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_agent_configs_type", "config_type"),
        Index("idx_agent_configs_active", "is_active"),
    )


class MonitorRecord(Base):
    """
    用量监控记录表

    持久化每次 LLM 调用的 token 消耗、延迟、费用等指标
    """

    __tablename__ = "monitor_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"), nullable=False)
    cost_cny: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"), nullable=False)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    error: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)

    __table_args__ = (
        Index("idx_monitor_records_time", "time"),
        Index("idx_monitor_records_feature", "feature"),
    )
