# RAG 查询：检索相关文档 + 生成有来源标注的回答
from langchain_core.prompts import ChatPromptTemplate

from ..model import chat_model
from .ingest import get_vector_store
from ...utils.logger import logger

SIMILARITY_THRESHOLD = 0.3

RAG_SYSTEM = """你是 WorkMind AI 知识库助手。

规则：
1. 只根据下方提供的参考文档回答问题，不使用文档之外的知识
2. 如果文档中没有相关内容，明确说"知识库中未找到相关内容"
3. 回答要准确、简洁，必要时列出要点
4. 在回答末尾用 【来源：文档名】 标注使用了哪些文档"""


async def retrieve_docs(question, category=None, k=4):
    vs = await get_vector_store()

    filter_fn = None
    if category:
        filter_fn = lambda content, meta: meta.get('category') == category

    results = await vs.similarity_search_with_score(question, k, filter_fn)

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
    options = options or {}
    docs = await retrieve_docs(question, category=options.get('category'))

    async def stream_answer():
        if not docs:
            yield '知识库中未找到与该问题相关的内容。\n请尝试换一种提问方式，或上传相关文档后再试。'
            return

        context = '\n\n---\n\n'.join(
            f'[参考{i + 1}] 来源：{d["title"]}\n{d["content"]}'
            for i, d in enumerate(docs)
        )

        prompt = ChatPromptTemplate.from_messages([
            ('system', RAG_SYSTEM),
            ('human', '参考文档：\n{context}\n\n问题：{question}'),
        ])

        chain = prompt | chat_model
        async for chunk in chain.astream({'context': context, 'question': question}):
            if chunk.content:
                yield chunk.content

    return {'sources': docs, 'stream_answer': stream_answer}
