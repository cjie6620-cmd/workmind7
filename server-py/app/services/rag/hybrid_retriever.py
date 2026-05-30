"""
混合检索编排模块

使用 LangChain 的 EnsembleRetriever 将 BM25 和向量检索融合：
- BM25Retriever：关键词召回（jieba 中文分词）
- PGVectorRetriever：向量召回（pgvector 余弦相似度）
- EnsembleRetriever：RRF（Reciprocal Rank Fusion）自动融合

索引管理：
- BM25 索引惰性初始化，缓存在内存
- 文档增删时调用 mark_bm25_stale() 标记需要重建
"""

import jieba
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from ...config import config
from ...core.database import async_session_factory
from ...utils.logger import logger
from .retriever import PGVectorRetriever

# ── BM25 索引缓存 ──────────────────────────────────────────

_bm25_retriever = None
_bm25_category = None
_bm25_stale = True


async def _load_all_chunks(category=None):
    """
    从 PostgreSQL 加载所有 chunk 文本，转为 LangChain Document 列表

    用于构建 BM25 索引。
    """
    from sqlalchemy import select, text

    async with async_session_factory() as session:
        sql = """
            SELECT id, doc_id, chunk_index, content, metadata
            FROM rag_chunks
        """
        params = {}
        if category:
            sql += " WHERE metadata->>'category' = :category"
            params['category'] = category

        sql += " ORDER BY doc_id, chunk_index"
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    documents = []
    for row in rows:
        meta = row[4] if isinstance(row[4], dict) else {}
        doc = Document(
            page_content=row[3],
            metadata={
                **meta,
                'chunk_id': str(row[0]),
                'doc_id': str(row[1]),
                'chunk_index': row[2],
            },
        )
        documents.append(doc)

    logger.info('hybrid: loaded chunks for BM25', {
        'total': len(documents),
        'category': category or 'all',
    })
    return documents


def _jieba_tokenize(text: str) -> list:
    """jieba 中文分词，作为 BM25Retriever 的 preprocess_func"""
    return list(jieba.cut(text))


async def _build_bm25_retriever(category=None):
    """构建 BM25Retriever（从数据库加载 chunk，用 jieba 分词）"""
    global _bm25_retriever, _bm25_category, _bm25_stale

    docs = await _load_all_chunks(category)
    if not docs:
        logger.warn('hybrid: no chunks for BM25 index')
        _bm25_retriever = None
        return

    _bm25_retriever = BM25Retriever.from_documents(
        docs,
        k=config['rag']['bm25_recall_k'],
        preprocess_func=_jieba_tokenize,
    )
    _bm25_category = category
    _bm25_stale = False

    logger.info('hybrid: BM25 index built', {
        'chunks': len(docs),
        'category': category or 'all',
    })


def mark_bm25_stale():
    """标记 BM25 索引需要重建（文档增删后调用）"""
    global _bm25_stale
    _bm25_stale = True
    logger.info('hybrid: BM25 index marked stale')


async def get_hybrid_retriever(category=None):
    """
    获取混合检索器

    返回 EnsembleRetriever，内部自动执行 RRF 融合。

    流程：
    1. 检查 BM25 索引是否需要重建
    2. 构建向量检索器（PGVectorRetriever）
    3. 组合为 EnsembleRetriever（内置 RRF）
    """
    # 如果 BM25 索引需要重建（文档增删后），或 category 变化
    if _bm25_stale or _bm25_retriever is None or _bm25_category != category:
        await _build_bm25_retriever(category)

    rag_config = config['rag']

    # 向量检索器
    vector_retriever = PGVectorRetriever(
        k=rag_config['vector_recall_k'],
        category=category,
    )

    # 如果 BM25 索引为空（无文档），直接返回向量检索器
    if _bm25_retriever is None:
        logger.warn('hybrid: BM25 unavailable, using vector only')
        return vector_retriever

    # 更新 BM25 的 k 参数
    _bm25_retriever.k = rag_config['bm25_recall_k']

    # RRF 融合
    ensemble = EnsembleRetriever(
        retrievers=[vector_retriever, _bm25_retriever],
        weights=[0.5, 0.5],
        c=60,
    )

    return ensemble
