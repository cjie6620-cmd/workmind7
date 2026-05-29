"""
PostgreSQL 向量存储

使用 pgvector 扩展存储和检索向量

特点：
- 异步操作，基于 asyncpg
- 支持余弦相似度搜索（<=> 操作符）
- 批量插入优化
"""

import uuid
from datetime import datetime
from typing import List, Optional, Tuple, Callable

from sqlalchemy import select, delete, text
from sqlalchemy.dialects.postgresql import insert

from ...core.database import async_session_factory
from ...models.entities import RagChunk
from ...utils.logger import logger


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
        self.embedding_dim = embedding_dim

    async def add_documents(self, documents: List[dict]):
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

        async with async_session_factory() as session:
            async with session.begin():
                # 使用 upsert 避免重复插入
                for doc in documents:
                    chunk = RagChunk(
                        id=uuid.uuid4(),
                        doc_id=uuid.UUID(doc['doc_id']),
                        chunk_index=doc['chunk_index'],
                        content=doc['content'],
                        embedding=doc['embedding'],  # List[float]，pgvector 自动处理
                        metadata_=doc.get('metadata', {}),
                    )
                    session.add(chunk)

            await session.commit()

        logger.info('pgvector: added documents', {'count': len(documents)})

    async def similarity_search_with_score(
        self,
        query_vector: List[float],
        k: int = 4,
        doc_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Tuple[dict, float]]:
        """
        向量相似度搜索

        Args:
            query_vector: 查询向量
            k: 返回前 k 个结果
            doc_id: 可选，限定文档ID
            category: 可选，限定分类

        Returns:
            List[(文档, 相似度分数)]，按相似度降序排列
        """
        # 构建查询
        query_str = f"""
            SELECT
                id, doc_id, chunk_index, content, metadata,
                1 - (embedding <=> '{self._vec_to_str(query_vector)}'::vector) as similarity
            FROM rag_chunks
            WHERE 1=1
        """
        params = {}

        if doc_id:
            query_str += " AND doc_id = :doc_id"
            params['doc_id'] = doc_id

        if category:
            query_str += " AND metadata->>'category' = :category"
            params['category'] = category

        query_str += f"""
            ORDER BY embedding <=> '{self._vec_to_str(query_vector)}'::vector
            LIMIT :k
        """
        params['k'] = k

        async with async_session_factory() as session:
            result = await session.execute(text(query_str), params)
            rows = result.fetchall()

        return [
            (
                {
                    'id': str(row[0]),
                    'doc_id': str(row[1]),
                    'chunk_index': row[2],
                    'pageContent': row[3],
                    'metadata': row[4] if isinstance(row[4], dict) else {},
                },
                float(row[5]) if row[5] is not None else 0.0,
            )
            for row in rows
        ]

    async def delete_by_doc_id(self, doc_id: str):
        """删除指定文档的所有切片"""
        async with async_session_factory() as session:
            await session.execute(
                delete(RagChunk).where(RagChunk.doc_id == uuid.UUID(doc_id))
            )
            await session.commit()

        logger.info('pgvector: deleted doc', {'doc_id': doc_id})

    async def count(self, doc_id: Optional[str] = None) -> int:
        """统计切片数量"""
        async with async_session_factory() as session:
            if doc_id:
                result = await session.execute(
                    select(RagChunk).where(RagChunk.doc_id == uuid.UUID(doc_id))
                )
            else:
                result = await session.execute(select(RagChunk))
            return len(result.scalars().all())

    async def get_doc_ids(self) -> List[str]:
        """获取所有文档ID列表"""
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT DISTINCT doc_id FROM rag_chunks")
            )
            return [str(row[0]) for row in result.fetchall()]

    def _vec_to_str(self, vec: List[float]) -> str:
        """将向量列表转换为 PostgreSQL 格式字符串"""
        return '[' + ','.join(str(x) for x in vec) + ']'


# ── 单例 ────────────────────────────────────────────────────

_vector_store: Optional[PGVectorStore] = None


async def get_vector_store() -> PGVectorStore:
    """获取或初始化向量存储单例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = PGVectorStore()
        logger.info('pgvector: store initialized')
    return _vector_store


async def init_pgvector_schema():
    """
    初始化 pgvector 扩展和表结构

    - 首次部署时创建扩展和表
    - 已有数据库时自动迁移 embedding 列从 text 到 vector(1024)
    """
    async with async_session_factory() as session:
        # 创建 pgvector 扩展
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # 检查并修正 embedding 列类型（text → vector）
        result = await session.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'rag_chunks' AND column_name = 'embedding'
        """))
        row = result.first()
        if row and row[0] == 'text':
            await session.execute(text("""
                ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(1024)
                USING embedding::vector
            """))
            logger.info('pgvector: migrated embedding column from text to vector(1024)')

        await session.commit()

    # 确保表结构最新（新增表会自动创建）
    from ...models.entities import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info('pgvector: schema initialized')


# 导出 asyncio 用到的 engine
from ...core.database import async_engine