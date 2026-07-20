"""
PostgreSQL 向量存储

使用 pgvector 扩展存储和检索向量

特点：
- SQLAlchemy async 会话（底层 asyncpg 驱动），全部参数化查询
- 余弦相似度搜索（<=> 操作符走 HNSW 索引），支持 category/owner 过滤下推
- 批量插入优化
"""

import math
import uuid
from numbers import Real
from typing import List, Optional, Tuple

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import async_session_factory
from ...models.entities import RagChunk
from ...utils.logger import logger

MAX_SEARCH_K = 100


class PGVectorStore:
    """
    PostgreSQL 向量存储

    使用 pgvector 的 cosine distance 进行相似度搜索
    """

    def __init__(self, embedding_dim: int = 1024):
        """
        初始化向量存储

        Args:
            embedding_dim: 向量维度（默认 1024，对应 bge-m3）
        """
        if isinstance(embedding_dim, bool) or not isinstance(embedding_dim, int) or embedding_dim <= 0:
            raise ValueError("embedding_dim 必须是正整数")
        self.embedding_dim = embedding_dim

    async def add_documents(
        self,
        documents: List[dict],
        *,
        session: AsyncSession | None = None,
    ):
        """
        批量添加文档切片

        Args:
            documents: 文档列表，每个包含:
                - doc_id: 文档ID
                - chunk_index: 切片序号
                - content: 文本内容
                - embedding: 向量列表（List[float]）
                - metadata: 元数据字典
        """
        if not documents:
            return

        chunks = []
        for doc in documents:
            try:
                doc_uuid = uuid.UUID(str(doc["doc_id"]))
            except (KeyError, TypeError, ValueError) as err:
                raise ValueError("doc_id 必须是合法 UUID") from err

            chunk_index = doc.get("chunk_index")
            if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 0:
                raise ValueError("chunk_index 必须是非负整数")

            chunks.append(
                RagChunk(
                    id=uuid.uuid4(),
                    doc_id=doc_uuid,
                    chunk_index=chunk_index,
                    content=doc["content"],
                    embedding=self._normalize_vector(doc["embedding"]),
                    metadata_=doc.get("metadata", {}),
                )
            )

        if session is not None:
            session.add_all(chunks)
        else:
            async with async_session_factory() as owned_session:
                async with owned_session.begin():
                    owned_session.add_all(chunks)

        logger.info("pgvector: added documents", {"count": len(documents)})

    async def similarity_search_with_score(
        self,
        query_vector: List[float],
        k: int = 4,
        doc_id: Optional[str] = None,
        category: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ) -> List[Tuple[dict, float]]:
        """
        向量相似度搜索

        Args:
            query_vector: 查询向量
            k: 返回前 k 个结果
            doc_id: 可选，限定文档ID
            category: 可选，限定分类
            owner_user_id: 可选，按上传者隔离（NULL owner 为共享文档，对所有人可见）；
                传入后过滤下推到 SQL，避免召回被其他租户文档挤占（recall starvation）。

        Returns:
            List[(文档, 相似度分数)]，按相似度降序排列
        """
        query_vector = self._normalize_vector(query_vector)
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_SEARCH_K:
            raise ValueError(f"k 必须在 1 到 {MAX_SEARCH_K} 之间")

        # 向量作为带 pgvector 类型的绑定参数传递，不拼接到 SQL 文本。
        query_str = """
            SELECT
                id, doc_id, chunk_index, content, metadata,
                1 - (embedding <=> :query_vector) as similarity
            FROM rag_chunks
            WHERE 1=1
        """
        params = {"query_vector": query_vector, "k": k}

        if doc_id:
            try:
                doc_uuid = uuid.UUID(str(doc_id))
            except (TypeError, ValueError) as err:
                raise ValueError("doc_id 必须是合法 UUID") from err
            query_str += " AND doc_id = :doc_id"
            params["doc_id"] = doc_uuid

        if category:
            query_str += " AND metadata->>'category' = :category"
            params["category"] = category

        if owner_user_id is not None:
            query_str += " AND (metadata->>'ownerUserId' IS NULL OR metadata->>'ownerUserId' = :owner_user_id)"
            params["owner_user_id"] = str(owner_user_id)

        query_str += """
            ORDER BY embedding <=> :query_vector
            LIMIT :k
        """
        statement = text(query_str).bindparams(bindparam("query_vector", type_=Vector(self.embedding_dim)))

        async with async_session_factory() as session:
            result = await session.execute(statement, params)
            rows = result.fetchall()

        return [
            (
                {
                    "id": str(row[0]),
                    "doc_id": str(row[1]),
                    "chunk_index": row[2],
                    "pageContent": row[3],
                    "metadata": row[4] if isinstance(row[4], dict) else {},
                },
                float(row[5]) if row[5] is not None else 0.0,
            )
            for row in rows
        ]

    async def delete_by_doc_id(
        self,
        doc_id: str,
        *,
        session: AsyncSession | None = None,
    ):
        """删除指定文档的所有切片"""
        try:
            doc_uuid = uuid.UUID(str(doc_id))
        except (TypeError, ValueError) as err:
            raise ValueError("doc_id 必须是合法 UUID") from err

        statement = delete(RagChunk).where(RagChunk.doc_id == doc_uuid)
        if session is not None:
            await session.execute(statement)
        else:
            async with async_session_factory() as owned_session:
                async with owned_session.begin():
                    await owned_session.execute(statement)

        logger.info("pgvector: deleted doc", {"doc_id": doc_id})

    def _normalize_vector(self, vector: List[float]) -> List[float]:
        """校验向量维度和数值边界，并归一为 Python float 列表。"""
        if not isinstance(vector, (list, tuple)) or len(vector) != self.embedding_dim:
            raise ValueError(f"向量维度必须为 {self.embedding_dim}")

        normalized: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError("向量元素必须是有限数值")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("向量元素必须是有限数值")
            normalized.append(number)
        return normalized


# ── 单例 ────────────────────────────────────────────────────

_vector_store: Optional[PGVectorStore] = None


async def get_vector_store() -> PGVectorStore:
    """获取或初始化向量存储单例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = PGVectorStore()
        logger.info("pgvector: store initialized")
    return _vector_store


async def init_pgvector_schema():
    """
    确保 pgvector 扩展可用，并迁移 embedding 列类型（开发环境兼容）。

    表结构由 Alembic 管理，不在此自动建表。
    """
    async with async_session_factory() as session:
        # 创建 pgvector 扩展
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # 检查并修正 embedding 列类型（text → vector）
        result = await session.execute(
            text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'rag_chunks' AND column_name = 'embedding'
        """)
        )
        row = result.first()
        if row and row[0] == "text":
            await session.execute(
                text("""
                ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(1024)
                USING embedding::vector
            """)
            )
            logger.info("pgvector: migrated embedding column from text to vector(1024)")

        await session.commit()

    logger.info("pgvector: extension ready (tables via alembic upgrade head)")
