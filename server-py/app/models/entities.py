"""
SQLAlchemy ORM 模型定义

对应 PostgreSQL 表结构（含 pgvector 向量列）。约定：
- 所有 DateTime 均存 UTC-naive（业务时区转换见 utils/business_time.py）
- 表结构变更走 alembic 迁移，ORM 声明与迁移必须保持一致
- 每个字段带 comment 说明业务含义（随建表写入数据库 COMMENT）
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
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

    知识库文档元信息；切片正文与向量在 rag_chunks，随本表级联删除
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="文档唯一 ID"
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="文档标题（展示用）")
    file_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="原始文件名（文本入库时为生成名）")
    category: Mapped[str] = mapped_column(
        String(64),
        default="通用",
        server_default=text("'通用'"),
        nullable=False,
        comment="文档分类，检索时可按分类过滤",
    )
    chunks: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False, comment="切片数量（入库时统计）"
    )
    chars: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False, comment="正文字符数（入库时统计）"
    )
    preview: Mapped[str] = mapped_column(Text, nullable=True, comment="正文预览片段（列表页展示）")
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
        comment="入库时间",
    )

    __table_args__ = (Index("idx_documents_owner_created", "owner_user_id", "created_at"),)


class RagChunk(Base):
    """
    RAG 知识库切片表

    存储文档切片正文与向量嵌入；metadata 冗余 title/category/ownerUserId
    等字段供检索层过滤下推，避免与 documents 表 join
    """

    __tablename__ = "rag_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="切片唯一 ID"
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", name="fk_rag_chunks_document", ondelete="CASCADE"),
        nullable=False,
        comment="所属文档 ID，文档删除时级联删除切片",
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="切片在文档内的序号（0 起）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切片正文")
    # pgvector 向量类型（bge-m3 输出维度 1024）；NULL 表示嵌入生成失败待补
    embedding = mapped_column(Vector(1024), nullable=True, comment="bge-m3 语义向量（1024 维）")
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
        comment="检索用元数据：title/category/ownerUserId/docId 等",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="更新时间；MAX(updated_at) 作为 BM25 索引版本号",
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
        # BM25 版本探测用 MAX(updated_at)，按分类过滤用 metadata->>'category'；补索引避免全表扫描
        Index("idx_rag_chunks_updated_at", "updated_at"),
        Index("idx_rag_chunks_category", text("(metadata ->> 'category')")),
        UniqueConstraint("doc_id", "chunk_index", name="uq_rag_chunks_doc_chunk"),
    )


class Conversation(Base):
    """
    对话历史表

    一行一条消息；会话由 session_id 聚合（前缀区分 chat/agent/knowledge）
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="消息唯一 ID"
    )
    session_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="会话 ID，格式 {session_|agent_|knowledge_}{userId}_{suffix}"
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.id", name="fk_conversations_user", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属用户 ID",
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="消息角色：user / assistant / system")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息正文")
    model: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="生成该回复的模型名（用户消息为空）"
    )
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="估算 token 数（上下文裁剪用）")
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
        comment="扩展元数据：引用来源、反馈评价等",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="消息时间",
    )

    __table_args__ = (Index("idx_conversations_session", "session_id", "created_at"),)


class ApprovalRecord(Base):
    """
    审批记录表

    ERP 审批流程演练的完整记录（一个 session 一条记录，request_id 幂等去重）
    """

    __tablename__ = "approval_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="审批记录唯一 ID"
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="发起审批的会话 ID（唯一）")
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", name="fk_approval_records_user", ondelete="CASCADE"),
        nullable=False,
        comment="申请人用户 ID，由认证上下文写入",
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="客户端幂等请求 ID")
    form_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="表单类型：expense / leave")
    form_data: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="表单字段（金额/天数由服务端重算）")
    flow_json: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="审批链各节点的意见与结论")
    approvers: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="审批人列表（模拟角色）")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="状态：pending / approved / rejected / needs_info / failed"
    )
    final_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="终审意见汇总")
    result_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="完整流程输出快照")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="提交时间",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="流程完成时间")

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
        # 管理员列表按 created_at 全局排序，补单列索引服务 Top-N
        Index("idx_approval_created", "created_at"),
    )


class AgentConfig(Base):
    """
    Agent/工作流配置表

    统一存放 agent / workflow / prompt 三类运行时配置；
    version 为乐观并发修订号（非历史版本仓库）
    """

    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="配置唯一 ID"
    )
    config_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="配置类型：agent / workflow / prompt")
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, comment="配置名称（全局唯一）")
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="配置内容（按类型各自校验 schema）")
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False, comment="乐观锁修订号，每次更新 +1"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, comment="停用后阻止新任务启动（不追溯在途任务）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=text("timezone('UTC', CURRENT_TIMESTAMP)"),
        nullable=False,
        comment="更新时间",
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

    # BigInteger 主键：每次 LLM 调用插一行，Integer(2^31) 会在高流量下溢出。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="自增主键")
    time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, comment="调用发生时间（UTC-naive）"
    )
    feature: Mapped[str] = mapped_column(String(32), nullable=False, comment="业务域：chat/agent/knowledge/erp 等")
    input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False, comment="输入 token 数"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False, comment="输出 token 数"
    )
    cost_usd: Mapped[float] = mapped_column(
        Float, default=0, server_default=text("0"), nullable=False, comment="本次调用费用（美元）"
    )
    cost_cny: Mapped[float] = mapped_column(
        Float, default=0, server_default=text("0"), nullable=False, comment="本次调用费用（人民币）"
    )
    latency_ms: Mapped[float] = mapped_column(
        Float, default=0, server_default=text("0"), nullable=False, comment="端到端延迟（毫秒）"
    )
    from_cache: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        comment="是否命中语义/精确缓存（未实际调模型）",
    )
    error: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, comment="调用是否失败（断连取消不计）"
    )

    __table_args__ = (
        Index("idx_monitor_records_time", "time"),
        Index("idx_monitor_records_feature", "feature"),
    )
