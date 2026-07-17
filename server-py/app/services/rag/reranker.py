"""
CrossEncoder 精排模块

使用 BAAI/bge-reranker-v2-m3 对候选文档进行精排（重打分）。
与 bge-m3 Embedding 模型同系列，天然搭配，支持中文。

使用方式：
- get_reranker() 获取单例
- reranker.rerank(query, documents, top_n) 获取精排结果
"""

from typing import List

from langchain_core.documents import Document

from ...config import config
from ...utils.logger import logger

# 精排分数阈值：低于此值的结果不返回
RERANK_THRESHOLD = config["rag"]["rerank_threshold"]


class CrossEncoderReranker:
    """
    基于 CrossEncoder 的精排器

    将 query 和每个候选文档组成 pair，通过 CrossEncoder 模型
    直接输出相关性分数，比双塔向量模型更精确。
    """

    def __init__(self, model_path: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_path, device=device)
        logger.info("reranker: model loaded", {"model": model_path, "device": device})

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_n: int = 4,
    ) -> List[dict]:
        """
        对候选文档进行精排

        Args:
            query: 用户问题
            documents: 候选文档列表（LangChain Document）
            top_n: 返回前 N 个结果

        Returns:
            精排后的文档列表，每个包含：
            - content: 文档内容
            - rerank_score: 精排分数
            - title: 文档标题
            - docId: 文档 ID
            - category: 分类
            - preview: 内容预览
        """
        if not documents:
            return []

        # 构建 (query, doc) pair 列表
        pairs = [(query, doc.page_content) for doc in documents]
        scores = self.model.predict(pairs)

        # 按分数降序排序
        doc_scores = list(zip(documents, scores))
        doc_scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for doc, score in doc_scores[:top_n]:
            score_val = float(score)
            if score_val < RERANK_THRESHOLD:
                continue
            results.append(
                {
                    "content": doc.page_content,
                    "rerank_score": round(score_val, 4),
                    "vector_score": doc.metadata.get("vector_score", 0),
                    "title": doc.metadata.get("title", "未知来源"),
                    "docId": doc.metadata.get("docId"),
                    "category": doc.metadata.get("category"),
                    "preview": doc.page_content[:80].replace("\n", " ") + "...",
                }
            )

        logger.info(
            "reranker: done",
            {
                "candidates": len(documents),
                "results": len(results),
                "topScore": f"{doc_scores[0][1]:.4f}" if doc_scores else "N/A",
            },
        )

        return results


# ── 单例（延迟加载）──────────────────────────────────────

_reranker = None


def get_reranker() -> CrossEncoderReranker:
    """获取精排器单例（首次调用时加载模型，约 560MB）"""
    global _reranker
    if _reranker is None:
        rag_config = config["rag"]
        _reranker = CrossEncoderReranker(
            model_path=rag_config["reranker_model"],
            device=rag_config["reranker_device"],
        )
    return _reranker
