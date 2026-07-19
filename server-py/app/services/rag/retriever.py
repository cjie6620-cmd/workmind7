"""
PGVector LangChain 检索器封装

将自定义 PGVectorStore 包装为 LangChain BaseRetriever，
以便与 EnsembleRetriever（RRF 融合）配合使用。
"""

import asyncio
from typing import List, Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from .pgvector_store import get_vector_store
from ...utils.logger import logger


class PGVectorRetriever(BaseRetriever):
    """
    基于 pgvector 的向量检索器（LangChain BaseRetriever 封装）

    用于与 EnsembleRetriever 配合，实现混合检索。
    """

    k: int = Field(default=20, description="返回文档数量")
    category: Optional[str] = Field(default=None, description="按分类过滤")
    owner_user_id: Optional[str] = Field(default=None, description="按上传者隔离（None 表示不限制/管理员）")

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        """同步检索（通过 asyncio.run 包装）"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有事件循环中（如 FastAPI），无法直接 run
            # 这种场景应使用 _aget_relevant_documents
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._async_search(query))
                return future.result()
        return asyncio.run(self._async_search(query))

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> List[Document]:
        """异步检索：调用 pgvector 余弦相似度搜索"""
        return await self._async_search(query)

    async def _async_search(self, query: str) -> List[Document]:
        """
        执行向量搜索，将结果转为 LangChain Document 列表

        保留 similarity score 在 Document.metadata 中，
        供后续 RRF 融合和日志使用。
        """
        from ..model import get_embeddings

        query_vec = await get_embeddings().aembed_query(query)
        vs = await get_vector_store()
        results = await vs.similarity_search_with_score(
            query_vector=query_vec,
            k=self.k,
            category=self.category,
            owner_user_id=self.owner_user_id,
        )

        documents: list[Document] = []
        for doc_dict, score in results:
            doc = Document(
                page_content=doc_dict["pageContent"],
                metadata={
                    **doc_dict.get("metadata", {}),
                    "chunk_id": doc_dict["id"],
                    "doc_id": doc_dict["doc_id"],
                    "chunk_index": doc_dict["chunk_index"],
                    "vector_score": round(score, 4),
                },
            )
            documents.append(doc)

        logger.info(
            "retriever: vector search done",
            {
                "query": query[:40],
                "k": self.k,
                "results": len(documents),
            },
        )

        return documents
