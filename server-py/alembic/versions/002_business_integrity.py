"""business ownership, idempotency and vector search indexes

Revision ID: 002_business_integrity
Revises: 001_baseline
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "002_business_integrity"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="账号是否允许登录和刷新令牌",
        ),
    )

    op.add_column(
        "documents",
        sa.Column("owner_user_id", sa.String(length=64), nullable=True, comment="上传者用户 ID"),
    )
    op.create_foreign_key(
        "fk_documents_owner",
        "documents",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_documents_owner_created",
        "documents",
        ["owner_user_id", "created_at"],
    )

    # 先为旧版孤儿切片补建最小文档元数据，禁止迁移通过静默删业务数据来满足 FK。
    op.execute(
        """
        INSERT INTO documents (
            id, title, file_name, category, chunks, chars, preview, created_at
        )
        SELECT
            chunk.doc_id::text,
            '迁移恢复文档 ' || left(chunk.doc_id::text, 8),
            'legacy-' || chunk.doc_id::text || '.txt',
            '迁移恢复',
            count(*)::integer,
            sum(length(chunk.content))::integer,
            left(min(chunk.content), 500),
            coalesce(min(chunk.created_at), timezone('UTC', CURRENT_TIMESTAMP))
        FROM rag_chunks AS chunk
        LEFT JOIN documents AS document ON lower(document.id) = chunk.doc_id::text
        WHERE document.id IS NULL
        GROUP BY chunk.doc_id
        """
    )

    # 基线曾允许任意 VARCHAR ID。有效 UUID 保持不变，其余 ID 映射为稳定 UUID，
    # 并同步切片 metadata 中用于引用展示的 docId。
    op.execute(
        """
        CREATE TEMPORARY TABLE document_id_migration_map (
            old_id varchar(64) PRIMARY KEY,
            new_id uuid NOT NULL UNIQUE
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        DO $migration$
        DECLARE
            source_record record;
            candidate uuid;
            digest text;
            attempt integer;
        BEGIN
            FOR source_record IN
                WITH parsed AS (
                    SELECT
                        id,
                        CASE
                            WHEN id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                                THEN id::uuid
                            ELSE NULL
                        END AS parsed_uuid
                    FROM documents
                ), ranked AS (
                    SELECT
                        id,
                        parsed_uuid,
                        row_number() OVER (
                            PARTITION BY parsed_uuid
                            ORDER BY (id = lower(id)) DESC, id
                        ) AS uuid_rank
                    FROM parsed
                )
                SELECT id, parsed_uuid, uuid_rank
                FROM ranked
                -- 先占用所有合法 UUID，再为大小写副本和非 UUID ID 寻找稳定候选。
                ORDER BY (parsed_uuid IS NOT NULL AND uuid_rank = 1) DESC, id
            LOOP
                IF source_record.parsed_uuid IS NOT NULL AND source_record.uuid_rank = 1 THEN
                    candidate := source_record.parsed_uuid;
                ELSE
                    attempt := 0;
                    LOOP
                        digest := md5(
                            'workmind-document:' || source_record.id ||
                            CASE WHEN attempt = 0 THEN '' ELSE ':' || attempt::text END
                        );
                        candidate := (
                            substr(digest, 1, 8) || '-' || substr(digest, 9, 4) || '-' ||
                            substr(digest, 13, 4) || '-' || substr(digest, 17, 4) || '-' ||
                            substr(digest, 21, 12)
                        )::uuid;
                        EXIT WHEN NOT EXISTS (
                            SELECT 1
                            FROM document_id_migration_map
                            WHERE new_id = candidate
                        );
                        attempt := attempt + 1;
                    END LOOP;
                END IF;

                INSERT INTO document_id_migration_map (old_id, new_id)
                VALUES (source_record.id, candidate);
            END LOOP;
        END
        $migration$;
        """
    )
    op.execute(
        """
        UPDATE rag_chunks AS chunk
        SET metadata = jsonb_set(
            CASE
                WHEN jsonb_typeof(chunk.metadata) = 'object' THEN chunk.metadata
                WHEN chunk.metadata IS NULL OR chunk.metadata = 'null'::jsonb THEN '{}'::jsonb
                ELSE jsonb_build_object('legacyMetadata', chunk.metadata)
            END,
            '{docId}',
            to_jsonb(chunk.doc_id::text),
            true
        )
        """
    )
    op.execute(
        """
        UPDATE documents AS document
        SET id = mapping.new_id::text
        FROM document_id_migration_map AS mapping
        WHERE document.id = mapping.old_id
        """
    )
    op.alter_column(
        "documents",
        "id",
        existing_type=sa.String(length=64),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="id::uuid",
    )

    # 旧版重复 chunk_index 通过稳定重编号保留全部内容，再建立唯一约束。
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                (row_number() OVER (
                    PARTITION BY doc_id
                    ORDER BY chunk_index, created_at NULLS LAST, id
                ) - 1)::integer AS new_chunk_index
            FROM rag_chunks
        )
        UPDATE rag_chunks AS chunk
        SET chunk_index = ranked.new_chunk_index
        FROM ranked
        WHERE chunk.id = ranked.id
        """
    )
    op.execute(
        """
        UPDATE documents AS document
        SET chunks = summary.chunk_count,
            chars = summary.char_count
        FROM (
            SELECT
                document_row.id AS doc_id,
                count(chunk.id)::integer AS chunk_count,
                coalesce(sum(length(chunk.content)), 0)::integer AS char_count
            FROM documents AS document_row
            LEFT JOIN rag_chunks AS chunk ON chunk.doc_id = document_row.id
            GROUP BY document_row.id
        ) AS summary
        WHERE document.id = summary.doc_id
        """
    )
    op.create_foreign_key(
        "fk_rag_chunks_document",
        "rag_chunks",
        "documents",
        ["doc_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_rag_chunks_doc_chunk",
        "rag_chunks",
        ["doc_id", "chunk_index"],
    )

    op.add_column(
        "approval_records",
        sa.Column("user_id", sa.String(length=64), nullable=True, comment="申请人用户 ID"),
    )
    op.add_column(
        "approval_records",
        sa.Column("request_id", sa.String(length=128), nullable=True, comment="客户端幂等请求 ID"),
    )

    # 历史记录无法可靠反推账号，归入仅管理员可见的 legacy 所有者。
    op.execute("UPDATE approval_records SET user_id = 'legacy' WHERE user_id IS NULL")
    # 旧版本可能有空值、毫秒 ID 碰撞或恰好占用迁移候选值。逐行寻找
    # 未占用的稳定候选，避免长度溢出或极端历史数据再次碰撞。
    op.execute("CREATE INDEX IF NOT EXISTS _migration_002_approval_session_lookup ON approval_records (session_id)")
    op.execute(
        """
        DO $migration$
        DECLARE
            target_record record;
            candidate varchar(128);
            attempt integer;
        BEGIN
            FOR target_record IN
                WITH ranked AS (
                    SELECT
                        id,
                        session_id,
                        row_number() OVER (
                            PARTITION BY session_id
                            ORDER BY created_at NULLS LAST, id
                        ) AS row_num
                    FROM approval_records
                )
                SELECT id
                FROM ranked
                WHERE session_id IS NULL OR session_id = '' OR row_num > 1
                ORDER BY id
            LOOP
                attempt := 0;
                LOOP
                    candidate := 'migration_002_' || target_record.id::text ||
                        CASE WHEN attempt = 0 THEN '' ELSE '_' || attempt::text END;
                    EXIT WHEN NOT EXISTS (
                        SELECT 1
                        FROM approval_records
                        WHERE session_id = candidate AND id <> target_record.id
                    );
                    attempt := attempt + 1;
                END LOOP;

                UPDATE approval_records
                SET session_id = candidate
                WHERE id = target_record.id;
            END LOOP;
        END
        $migration$;
        """
    )
    op.execute("DROP INDEX IF EXISTS _migration_002_approval_session_lookup")
    op.alter_column("approval_records", "user_id", nullable=False)
    op.alter_column("approval_records", "session_id", nullable=False)

    # 兼容由 init-db.sql 建出的旧库，所有索引都使用 IF EXISTS/IF NOT EXISTS。
    op.execute("DROP INDEX IF EXISTS idx_approval_session")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_session ON approval_records (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_approval_user_created ON approval_records (user_id, created_at)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_user_request "
        "ON approval_records (user_id, request_id) WHERE request_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_records (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_configs_type ON agent_configs (config_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_configs_active ON agent_configs (is_active)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_monitor_records_time ON monitor_records (time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_monitor_records_feature ON monitor_records (feature)")

    # pgvector cosine 查询必须有近似索引，否则数据增长后会退化为全表排序。
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw "
        "ON rag_chunks USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rag_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_monitor_records_feature")
    op.execute("DROP INDEX IF EXISTS idx_monitor_records_time")
    op.execute("DROP INDEX IF EXISTS idx_agent_configs_active")
    op.execute("DROP INDEX IF EXISTS idx_agent_configs_type")
    op.execute("DROP INDEX IF EXISTS uq_approval_user_request")
    op.execute("DROP INDEX IF EXISTS idx_approval_user_created")
    op.execute("DROP INDEX IF EXISTS idx_approval_status")
    op.execute("DROP INDEX IF EXISTS idx_approval_session")
    op.alter_column("approval_records", "session_id", nullable=True)
    op.drop_column("approval_records", "request_id")
    op.drop_column("approval_records", "user_id")
    op.drop_constraint("uq_rag_chunks_doc_chunk", "rag_chunks", type_="unique")
    op.drop_constraint("fk_rag_chunks_document", "rag_chunks", type_="foreignkey")
    op.alter_column(
        "documents",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=64),
        postgresql_using="id::text",
    )
    op.drop_index("idx_documents_owner_created", table_name="documents")
    op.drop_constraint("fk_documents_owner", "documents", type_="foreignkey")
    op.drop_column("documents", "owner_user_id")
    op.drop_column("users", "is_active")
