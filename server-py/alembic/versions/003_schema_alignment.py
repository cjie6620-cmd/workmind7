"""align nullable constraints and server defaults with ORM metadata

Revision ID: 003_schema_alignment
Revises: 002_business_integrity
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "003_schema_alignment"
down_revision: Union[str, None] = "002_business_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSON_OBJECT_DEFAULT = sa.text("'{}'::jsonb")
NOW_DEFAULT = sa.text("timezone('UTC', CURRENT_TIMESTAMP)")
ZERO_DEFAULT = sa.text("0")


def upgrade() -> None:
    # 001 基线允许多个业务必填列为 NULL。先按既有默认语义回填，
    # 再收紧约束，避免升级已有生产数据时直接失败。
    op.execute(
        "UPDATE users SET role = COALESCE(role, 'user'), "
        "created_at = COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE role IS NULL OR created_at IS NULL"
    )
    op.execute(
        "UPDATE system_settings SET value = COALESCE(value, '{}'::jsonb), "
        "updated_at = COALESCE(updated_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE value IS NULL OR updated_at IS NULL"
    )
    op.execute(
        "UPDATE documents SET category = COALESCE(category, '通用'), "
        "chunks = COALESCE(chunks, 0), chars = COALESCE(chars, 0), "
        "created_at = COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE category IS NULL OR chunks IS NULL OR chars IS NULL OR created_at IS NULL"
    )
    op.execute(
        "UPDATE rag_chunks SET metadata = COALESCE(metadata, '{}'::jsonb), "
        "created_at = COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)), "
        "updated_at = COALESCE(updated_at, created_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE metadata IS NULL OR created_at IS NULL OR updated_at IS NULL"
    )
    op.execute(
        "UPDATE conversations SET metadata = COALESCE(metadata, '{}'::jsonb), "
        "created_at = COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE metadata IS NULL OR created_at IS NULL"
    )
    op.execute(
        "UPDATE approval_records SET created_at = "
        "COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)) WHERE created_at IS NULL"
    )
    op.execute(
        "UPDATE agent_configs SET version = COALESCE(version, 1), "
        "is_active = COALESCE(is_active, true), "
        "created_at = COALESCE(created_at, timezone('UTC', CURRENT_TIMESTAMP)), "
        "updated_at = COALESCE(updated_at, created_at, timezone('UTC', CURRENT_TIMESTAMP)) "
        "WHERE version IS NULL OR is_active IS NULL OR created_at IS NULL OR updated_at IS NULL"
    )
    op.execute(
        "UPDATE monitor_records SET input_tokens = COALESCE(input_tokens, 0), "
        "output_tokens = COALESCE(output_tokens, 0), "
        "cost_usd = COALESCE(cost_usd, 0), cost_cny = COALESCE(cost_cny, 0), "
        "latency_ms = COALESCE(latency_ms, 0), "
        "from_cache = COALESCE(from_cache, false), error = COALESCE(error, false) "
        "WHERE input_tokens IS NULL OR output_tokens IS NULL OR cost_usd IS NULL "
        "OR cost_cny IS NULL OR latency_ms IS NULL OR from_cache IS NULL OR error IS NULL"
    )

    op.alter_column(
        "users",
        "id",
        existing_type=sa.String(64),
        comment="用户唯一标识，与 JWT sub 一致",
    )
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(20),
        nullable=False,
        server_default=sa.text("'user'"),
        comment="角色：user / admin",
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "system_settings",
        "value",
        existing_type=postgresql.JSONB(),
        nullable=False,
        server_default=JSON_OBJECT_DEFAULT,
        comment="配置值 JSON",
    )
    op.alter_column(
        "system_settings",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )

    op.alter_column(
        "documents",
        "category",
        existing_type=sa.String(64),
        nullable=False,
        server_default=sa.text("'通用'"),
    )
    op.alter_column(
        "documents",
        "chunks",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=ZERO_DEFAULT,
    )
    op.alter_column(
        "documents",
        "chars",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=ZERO_DEFAULT,
    )
    op.alter_column(
        "documents",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "documents",
        "owner_user_id",
        existing_type=sa.String(64),
        comment="上传者；NULL 表示迁移前的共享文档",
    )

    op.alter_column(
        "rag_chunks",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=False,
        server_default=JSON_OBJECT_DEFAULT,
    )
    op.alter_column(
        "rag_chunks",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "rag_chunks",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )

    op.alter_column(
        "conversations",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=False,
        server_default=JSON_OBJECT_DEFAULT,
    )
    op.alter_column(
        "conversations",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "conversations",
        "user_id",
        existing_type=sa.String(64),
        comment="所属用户 ID",
    )
    op.alter_column(
        "approval_records",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "approval_records",
        "user_id",
        existing_type=sa.String(64),
        comment="申请人用户 ID，由认证上下文写入",
    )

    op.alter_column(
        "agent_configs",
        "version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
    )
    op.alter_column(
        "agent_configs",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )
    op.alter_column(
        "agent_configs",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )
    op.alter_column(
        "agent_configs",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=NOW_DEFAULT,
    )

    for column_name, column_type, default in (
        ("input_tokens", sa.Integer(), ZERO_DEFAULT),
        ("output_tokens", sa.Integer(), ZERO_DEFAULT),
        ("cost_usd", sa.Float(), ZERO_DEFAULT),
        ("cost_cny", sa.Float(), ZERO_DEFAULT),
        ("latency_ms", sa.Float(), ZERO_DEFAULT),
        ("from_cache", sa.Boolean(), sa.false()),
        ("error", sa.Boolean(), sa.false()),
    ):
        op.alter_column(
            "monitor_records",
            column_name,
            existing_type=column_type,
            nullable=False,
            server_default=default,
        )


def downgrade() -> None:
    for column_name, column_type in (
        ("input_tokens", sa.Integer()),
        ("output_tokens", sa.Integer()),
        ("cost_usd", sa.Float()),
        ("cost_cny", sa.Float()),
        ("latency_ms", sa.Float()),
        ("from_cache", sa.Boolean()),
        ("error", sa.Boolean()),
    ):
        op.alter_column(
            "monitor_records",
            column_name,
            existing_type=column_type,
            nullable=True,
        )

    for column_name, column_type in (
        ("version", sa.Integer()),
        ("is_active", sa.Boolean()),
    ):
        op.alter_column(
            "agent_configs",
            column_name,
            existing_type=column_type,
            nullable=True,
        )
    for column_name in ("created_at", "updated_at"):
        op.alter_column(
            "agent_configs",
            column_name,
            existing_type=sa.DateTime(),
            nullable=True,
            server_default=None,
        )

    op.alter_column(
        "approval_records",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "approval_records",
        "user_id",
        existing_type=sa.String(64),
        comment="申请人用户 ID",
    )
    op.alter_column(
        "conversations",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "conversations",
        "user_id",
        existing_type=sa.String(64),
        comment=None,
    )
    op.alter_column(
        "conversations",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )

    for column_name in ("created_at", "updated_at"):
        op.alter_column(
            "rag_chunks",
            column_name,
            existing_type=sa.DateTime(),
            nullable=True,
            server_default=None,
        )
    op.alter_column(
        "rag_chunks",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )

    op.alter_column(
        "documents",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "documents",
        "owner_user_id",
        existing_type=sa.String(64),
        comment="上传者用户 ID",
    )
    for column_name, column_type in (
        ("category", sa.String(64)),
        ("chunks", sa.Integer()),
        ("chars", sa.Integer()),
    ):
        op.alter_column(
            "documents",
            column_name,
            existing_type=column_type,
            nullable=True,
        )

    op.alter_column(
        "system_settings",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "system_settings",
        "value",
        existing_type=postgresql.JSONB(),
        nullable=True,
        comment="配置值",
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(20),
        nullable=True,
        comment="角色",
    )
    op.alter_column(
        "users",
        "id",
        existing_type=sa.String(64),
        comment="用户唯一标识",
    )
