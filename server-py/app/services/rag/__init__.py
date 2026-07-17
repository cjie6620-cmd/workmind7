"""
RAG 模块

提供知识库检索增强功能：
- ingest: 文档入库（文本提取、分片、向量化）
- query: RAG 查询（向量检索 + 生成回答）
"""

from .ingest import ingest_document, get_doc_registry, delete_document, get_vector_store
from .query import rag_query_stream, retrieve_docs

__all__ = [
    "ingest_document",
    "get_doc_registry",
    "delete_document",
    "get_vector_store",
    "rag_query_stream",
    "retrieve_docs",
]
