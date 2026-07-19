"""
RAG 查询模块

RAG（Retrieval Augmented Generation）流程：
1. retrieve_docs: 混合检索（BM25 + 向量 + RRF 融合）+ CrossEncoder 精排
2. rag_query_stream: 基于检索结果生成回答

检索策略：
- 第一阶段：BM25 关键词召回 + pgvector 向量召回 → EnsembleRetriever RRF 融合
- 第二阶段：CrossEncoder（bge-reranker-v2-m3）精排重打分
- 阈值过滤后返回最终结果
"""

from langchain_core.prompts import ChatPromptTemplate

from ..model import get_chat_model
from .hybrid_retriever import get_hybrid_retriever
from .reranker import get_reranker
from ...config import config
from ...utils.logger import logger

# RAG 系统提示词
RAG_SYSTEM = """你是 Mr.Chen AI 知识库助手。

规则：
1. 只根据下方提供的参考文档回答问题，不使用文档之外的知识
2. 如果文档中没有相关内容，明确说"知识库中未找到相关内容"
3. 回答要准确、简洁，必要时列出要点
4. 在回答末尾用 【来源：文档名】 标注使用了哪些文档"""


async def retrieve_docs(question, category=None, k=None, *, owner_user_id=None, is_admin=False):
    """
    混合检索 + 精排

    参数：
    - question: 查询问题
    - category: 可选，按文档分类筛选
    - k: 返回结果数量（默认从配置读取）
    - owner_user_id / is_admin: 按上传者隔离检索结果

    返回：精排后的文档列表（按 rerank_score 降序）
    """
    from .ingest import doc_visible_to_user

    rag_config = config["rag"]
    if k is None:
        k = rag_config["final_k"]

    # ① 混合检索（BM25 + 向量 + RRF 融合）
    # 非 admin 时把 owner 过滤下推到检索层，避免召回被其他租户文档挤占。
    effective_owner = None if is_admin else owner_user_id
    retriever = await get_hybrid_retriever(category, owner_user_id=effective_owner)
    candidates = await retriever.ainvoke(question)

    # 第二步：精排前再按所有者过滤一次作为纵深防御（即便检索层未过滤也不泄漏）
    if not is_admin and owner_user_id is not None:
        candidates = [
            doc
            for doc in candidates
            if doc_visible_to_user(doc.metadata.get("ownerUserId"), user_id=owner_user_id, is_admin=False)
        ]

    if not candidates:
        logger.info(
            "rag: no candidates from hybrid retrieval",
            {
                "question": question[:40],
            },
        )
        return []

    logger.info(
        "rag: hybrid retrieval done",
        {
            "question": question[:40],
            "candidates": len(candidates),
        },
    )

    # ② CrossEncoder 精排（模型加载与打分都放线程池，避免首个请求卡住事件循环）
    import asyncio

    reranker = await asyncio.to_thread(get_reranker)
    ranked = await asyncio.to_thread(reranker.rerank, question, candidates, top_n=k)

    logger.info(
        "rag: retrieval complete",
        {
            "question": question[:40],
            "candidates": len(candidates),
            "results": len(ranked),
            "topScore": f"{ranked[0]['rerank_score']:.4f}" if ranked else "N/A",
        },
    )

    return ranked


async def rag_query_stream(question, options=None):
    """
    RAG 流式查询

    返回：
    - sources: 相关文档列表
    - stream_answer: 生成器，流式输出回答

    SSE 事件由路由层处理
    """
    options = options or {}
    docs = await retrieve_docs(
        question,
        category=options.get("category"),
        owner_user_id=options.get("owner_user_id"),
        is_admin=bool(options.get("is_admin")),
    )

    async def stream_answer():
        """流式生成回答"""
        if not docs:
            yield "知识库中未找到与该问题相关的内容。\n请尝试换一种提问方式，或上传相关文档后再试。"
            return

        # 构建上下文
        context = "\n\n---\n\n".join(f"[参考{i + 1}] 来源：{d['title']}\n{d['content']}" for i, d in enumerate(docs))

        # 构建 Prompt
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM),
                ("human", "参考文档：\n{context}\n\n问题：{question}"),
            ]
        )

        # 执行链
        chain = prompt | get_chat_model()
        async for chunk in chain.astream({"context": context, "question": question}):
            if chunk.content:
                yield chunk.content

    return {"sources": docs, "stream_answer": stream_answer}
