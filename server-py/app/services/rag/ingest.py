# 文档入库：上传 → 读取文本 → 分片 → 向量化 → 存入内存向量库
import math
import os
import uuid
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..model import embeddings
from ...utils.logger import logger

MAX_CHUNKS = 300


# ── 轻量内存向量库 ──────────────────────────────────────────

class MemoryVectorStore:
    def __init__(self):
        self.vectors = []  # [{ content, embedding, metadata }]

    async def add_documents(self, documents):
        texts = [d.page_content for d in documents]
        BATCH = 20
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            batch_docs = documents[i:i + BATCH]
            vecs = await embeddings.aembed_documents(batch)
            for j, vec in enumerate(vecs):
                self.vectors.append({
                    'content': batch[j],
                    'embedding': vec,
                    'metadata': batch_docs[j].metadata,
                })
            logger.info('rag: embedding progress', {
                'done': min(i + BATCH, len(texts)),
                'total': len(texts),
            })

    async def similarity_search_with_score(self, query, k=4, filter_fn=None):
        query_vec = await embeddings.aembed_query(query)

        pool = self.vectors
        if filter_fn:
            pool = [v for v in pool if filter_fn(v['content'], v['metadata'])]

        scored = []
        for v in pool:
            score = _cosine_sim(query_vec, v['embedding'])
            scored.append((v, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        return [({'pageContent': v['content'], 'metadata': v['metadata']}, s)
                for v, s in scored[:k]]


def _cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb else 0


# ── 向量库单例 ──────────────────────────────────────────────

_vector_store = None


async def get_vector_store():
    global _vector_store
    if _vector_store:
        return _vector_store
    if not embeddings:
        raise RuntimeError('未配置 ZHIPU_API_KEY，无法使用 RAG 功能')
    _vector_store = MemoryVectorStore()
    logger.info('rag: memory vector store initialized')
    return _vector_store


# ── 文档注册表 ──────────────────────────────────────────────

_doc_registry = {}


def get_doc_registry():
    return list(_doc_registry.values())


def get_doc(doc_id):
    return _doc_registry.get(doc_id)


# ── 文本提取 ────────────────────────────────────────────────

async def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()

    if ext in ('.txt', '.md'):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    if ext == '.pdf':
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            return '\n'.join(page.extract_text() or '' for page in reader.pages)
        except Exception as e:
            logger.warn('pdf-parse failed', {'error': str(e)})
            raise RuntimeError(f'PDF 解析失败：{e}')

    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


# ── 核心：文档入库 ──────────────────────────────────────────

async def ingest_document(file_path, file_name, title=None, category='通用'):
    doc_id = f'doc_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:5]}'
    logger.info('rag: ingesting document', {'docId': doc_id, 'title': title, 'category': category})

    raw_text = await extract_text(file_path)
    if not raw_text.strip():
        raise RuntimeError('文档内容为空，无法处理')

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=['\n\n', '\n', '。', '；', '，', ' ', ''],
    )

    from langchain_core.documents import Document
    metadata = {
        'docId': doc_id,
        'title': title or file_name,
        'category': category,
        'fileName': file_name,
        'uploadedAt': datetime.now(timezone.utc).isoformat(),
    }
    chunks = splitter.create_documents([raw_text], metadatas=[metadata])

    if len(chunks) > MAX_CHUNKS:
        logger.warn('rag: too many chunks, truncating', {
            'original': len(chunks), 'truncated': MAX_CHUNKS,
        })
        chunks = chunks[:MAX_CHUNKS]

    logger.info('rag: document split', {'docId': doc_id, 'chunks': len(chunks)})

    vs = await get_vector_store()
    await vs.add_documents(chunks)

    doc_meta = {
        'id': doc_id,
        'title': title or file_name,
        'fileName': file_name,
        'category': category,
        'chunks': len(chunks),
        'chars': len(raw_text),
        'uploadedAt': datetime.now(timezone.utc).isoformat(),
        'preview': raw_text[:120].replace('\n', ' ') + '...',
    }
    _doc_registry[doc_id] = doc_meta

    # 清理临时文件
    try:
        os.unlink(file_path)
    except OSError:
        pass

    logger.info('rag: ingest complete', {'docId': doc_id, 'chunks': len(chunks)})
    return doc_meta


async def delete_document(doc_id):
    if doc_id not in _doc_registry:
        raise ValueError('文档不存在')

    global _vector_store
    if _vector_store:
        _vector_store.vectors = [
            v for v in _vector_store.vectors
            if v['metadata'].get('docId') != doc_id
        ]

    del _doc_registry[doc_id]
    logger.info('rag: document deleted', {'docId': doc_id})
