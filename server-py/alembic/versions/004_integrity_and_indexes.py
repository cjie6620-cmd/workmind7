"""add user_id FKs, widen monitor id, and index BM25/approval hot paths

Revision ID: 004_integrity_and_indexes
Revises: 003_schema_alignment
Create Date: 2026-07-20

变更内容：
- conversations.user_id / approval_records.user_id 补外键（此前只有 documents 有）。
  对已有脏数据安全：conversations 先把孤儿 user_id 置 NULL 再建 SET NULL 外键；
  approval_records.user_id 非空且不可置 NULL，用 NOT VALID 外键，仅对新数据强制、
  不校验历史行，避免升级失败。
- monitor_records.id 由 int4 扩宽为 bigint（高流量下 2^31 会溢出，widening 无损）。
- 为 BM25 版本探测（MAX(updated_at)）、分类过滤（metadata->>'category'）、
  审批管理员列表（created_at 全局排序）补索引。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_integrity_and_indexes"
down_revision: Union[str, None] = "003_schema_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. conversations.user_id 外键（SET NULL）。先清孤儿引用为 NULL，避免建约束失败。
    op.execute(
        "UPDATE conversations SET user_id = NULL WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM users)"
    )
    op.create_foreign_key(
        "fk_conversations_user",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. approval_records.user_id 外键（CASCADE）。列非空不可置 NULL，用 NOT VALID
    #    只对新数据强制，历史脏数据不阻断升级。
    op.execute(
        "ALTER TABLE approval_records "
        "ADD CONSTRAINT fk_approval_records_user "
        "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE NOT VALID"
    )

    # 3. monitor_records.id int4 → bigint（无损扩宽）
    op.alter_column(
        "monitor_records",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    # 4. 热点查询索引
    op.create_index("idx_rag_chunks_updated_at", "rag_chunks", ["updated_at"])
    op.execute("CREATE INDEX idx_rag_chunks_category ON rag_chunks ((metadata ->> 'category'))")
    op.create_index("idx_approval_created", "approval_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_approval_created", table_name="approval_records")
    op.execute("DROP INDEX IF EXISTS idx_rag_chunks_category")
    op.drop_index("idx_rag_chunks_updated_at", table_name="rag_chunks")

    op.alter_column(
        "monitor_records",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )

    op.drop_constraint("fk_approval_records_user", "approval_records", type_="foreignkey")
    op.drop_constraint("fk_conversations_user", "conversations", type_="foreignkey")
