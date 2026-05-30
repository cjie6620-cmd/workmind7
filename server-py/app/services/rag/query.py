"""
RAG 查询模块

RAG（Retrieval Augmented Generation）流程：
1. retrieve_docs: 使用 pgvector 检索相关文档
2. rag_query_stream: 基于检索结果生成回答

特点：
- 使用 PostgreSQL + pgvector 进行向量检索
- 相似度阈值过滤（默认 0.3）
- 支持按分类筛选
"""

from langchain_core.prompts import ChatPromptTemplate

from ..model import get_chat_model, get_embeddings
from .pgvector_store import get_vector_store
from ...utils.logger import logger

# 相似度阈值：低于此值的文档不返回
SIMILARITY_THRESHOLD = 0.3

# RAG 系统提示词
RAG_SYSTEM = """你是 Mr.Chen AI 知识库助手。

规则：
1. 只根据下方提供的参考文档回答问题，不使用文档之外的知识
2. 如果文档中没有相关内容，明确说"知识库中未找到相关内容"
3. 回答要准确、简洁，必要时列出要点
4. 在回答末尾用 【来源：文档名】 标注使用了哪些文档"""


async def retrieve_docs(question, category=None, k=4):
    """
    检索相关文档

    参数：
    - question: 查询问题
    - category: 可选，按文档分类筛选
    - k: 返回前 k 个结果

    返回：相关文档列表（已按相似度排序）
    """
    # 1. 将问题向量化
    query_vec = await get_embeddings().aembed_query(question)

    # 2. 使用 pgvector 搜索
    vs = await get_vector_store()
    results = await vs.similarity_search_with_score(
        query_vector=query_vec,
        k=k,
        category=category,
    )

    # 3. 过滤低相似度结果
    relevant = [(doc, score) for doc, score in results if score > SIMILARITY_THRESHOLD]

    logger.info('rag: retrieved docs', {
        'question': question[:40],
        'total': len(results),
        'relevant': len(relevant),
        'topScore': f'{results[0][1]:.3f}' if results else 'N/A',
    })

    return [{
        'content': doc['pageContent'],
        'score': round(score, 3),
        'title': doc['metadata'].get('title', '未知来源'),
        'docId': doc['metadata'].get('docId'),
        'category': doc['metadata'].get('category'),
        'preview': doc['pageContent'][:80].replace('\n', ' ') + '...',
    } for doc, score in relevant]


async def rag_query_stream(question, options=None):
    """
    RAG 流式查询

    返回：
    - sources: 相关文档列表
    - stream_answer: 生成器，流式输出回答

    SSE 事件由路由层处理
    """
    options = options or {}
    docs = await retrieve_docs(question, category=options.get('category'))

    async def stream_answer():
        """流式生成回答"""
        if not docs:
            yield '知识库中未找到与该问题相关的内容。\n请尝试换一种提问方式，或上传相关文档后再试。'
            return

        # 构建上下文
        context = '\n\n---\n\n'.join(
            f'[参考{i + 1}] 来源：{d["title"]}\n{d["content"]}'
            for i, d in enumerate(docs)
        )

        # 构建 Prompt
        prompt = ChatPromptTemplate.from_messages([
            ('system', RAG_SYSTEM),
            ('human', '参考文档：\n{context}\n\n问题：{question}'),
        ])

        # 执行链
        chain = prompt | get_chat_model()
        async for chunk in chain.astream({'context': context, 'question': question}):
            if chunk.content:
                yield chunk.content

    return {'sources': docs, 'stream_answer': stream_answer}