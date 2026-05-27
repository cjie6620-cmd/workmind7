"""
RAG 文档入库模块

文档处理流程：
1. 文件保存到本地
2. 提取文本（支持 .txt/.md/.pdf）
3. 文本分片（RecursiveCharacterTextSplitter）
4. 向量化（本地 sentence-transformers）
5. 存入向量库（内存向量库）
6. 更新文档注册表
7. 清理临时文件
"""

import asyncio
import math
import os
import uuid
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..model import get_embeddings
from ...utils.logger import logger

# 分片上限
MAX_CHUNKS = 300


# ── 轻量内存向量库 ──────────────────────────────────────────

class MemoryVectorStore:
    """
    内存向量库

    使用余弦相似度进行向量检索。
    适用于小规模场景（< 10万文档）。
    生产环境建议使用 Chroma、Pinecone 等专业向量库。
    """

    def __init__(self):
        self.vectors = []  # [{ content, embedding, metadata }]

    async def add_documents(self, documents):
        """批量添加文档（分批向量化，降低内存峰值）"""
        texts = [d.page_content for d in documents]
        BATCH = 5  # 小批次，减少单批内存占用
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            batch_docs = documents[i:i + BATCH]
            # 批量向量化
            vecs = await get_embeddings().aembed_documents(batch)
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
        """
        向量相似度搜索

        参数：
        - query: 查询文本
        - k: 返回前 k 个结果
        - filter_fn: 可选的过滤函数

        返回：[(文档, 相似度分数), ...]
        """
        query_vec = await get_embeddings().aembed_query(query)

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
    """计算余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na * nb else 0


# ── 向量库单例 ──────────────────────────────────────────────

_vector_store = None


async def get_vector_store():
    """获取或初始化向量库单例"""
    global _vector_store
    if _vector_store:
        return _vector_store
    _vector_store = MemoryVectorStore()
    logger.info('rag: memory vector store initialized')
    return _vector_store


# ── 文档注册表 ──────────────────────────────────────────────

# 内存存储文档元信息
_doc_registry = {}


def get_doc_registry():
    """获取所有文档元信息"""
    return list(_doc_registry.values())


def get_doc(doc_id):
    """获取指定文档元信息"""
    return _doc_registry.get(doc_id)


# ── 文本提取 ────────────────────────────────────────────────

def _extract_text_from_parse(result):
    """递归从 MinerU parse 结果中提取所有文本字符串"""
    texts = []
    if isinstance(result, str):
        texts.append(result)
    elif isinstance(result, dict):
        for v in result.values():
            texts.extend(_extract_text_from_parse(v))
    elif isinstance(result, list):
        for item in result:
            texts.extend(_extract_text_from_parse(item))
    return texts


def _extract_pdf_by_pypdf(file_path):
    """使用 pypdf 提取 PDF 文本（fallback 方案）"""
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


async def _extract_pdf_by_mineru(file_path):
    """通过 MinerU KIE SDK 提取 PDF 文本，失败时 fallback 到 pypdf"""
    from ...config import config

    mc = config.get('mineru', {})
    pipeline_id = mc.get('pipeline_id', '')
    base_url = mc.get('base_url', 'https://mineru.net/api/kie')
    api_key = mc.get('api_key', '')
    timeout = mc.get('timeout', 120)

    if not pipeline_id:
        logger.warn('mineru: pipeline_id 未配置，fallback 到 pypdf')
        return _extract_pdf_by_pypdf(file_path)

    if not api_key:
        logger.warn('mineru: api_key 未配置，fallback 到 pypdf')
        return _extract_pdf_by_pypdf(file_path)

    def _sync():
        from mineru_kie_sdk import MineruKIEClient
        client = MineruKIEClient(base_url=base_url, pipeline_id=pipeline_id, timeout=timeout)
        client.headers['Authorization'] = f'Bearer {api_key}'
        file_ids = client.upload_file(file_path)
        results = client.get_result(file_ids=file_ids, timeout=timeout, poll_interval=5)
        parse_result = results.get('parse')
        if parse_result is None:
            raise RuntimeError('MinerU 返回解析结果为空')
        # 尝试通过 get_result() 方法获取结构化数据
        result_obj = parse_result.get_result() if hasattr(parse_result, 'get_result') else parse_result
        texts = _extract_text_from_parse(result_obj)
        return '\n'.join(texts)

    try:
        return await asyncio.to_thread(_sync)
    except Exception as e:
        logger.warn('mineru: 调用失败，fallback 到 pypdf', {'error': str(e)})
        return _extract_pdf_by_pypdf(file_path)


async def extract_text(file_path):
    """
    从文件提取文本内容

    支持格式：
    - .txt: 纯文本，直接读取
    - .md: Markdown 文本，直接读取
    - .pdf: 优先使用 MinerU SDK，失败时 fallback 到 pypdf
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in ('.txt', '.md'):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    if ext == '.pdf':
        return await _extract_pdf_by_mineru(file_path)

    # 默认当作文本处理
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


# ── 核心：文档入库 ──────────────────────────────────────────

async def ingest_document(file_path, file_name, title=None, category='通用'):
    """
    文档入库核心函数

    参数：
    - file_path: 文件路径
    - file_name: 原始文件名
    - title: 文档标题（默认使用文件名）
    - category: 文档分类

    返回：文档元信息
    """
    doc_id = f'doc_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:5]}'
    logger.info('rag: ingesting document', {'docId': doc_id, 'title': title, 'category': category})

    # 1. 提取文本
    raw_text = await extract_text(file_path)
    if not raw_text.strip():
        raise RuntimeError('文档内容为空，无法处理')

    # 2. 文本分片
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,       # 每片 500 字符
        chunk_overlap=50,     # 重叠 50 字符，保持上下文连贯
        separators=['\n\n', '\n', '。', '；', '，', ' ', ''],
    )

    metadata = {
        'docId': doc_id,
        'title': title or file_name,
        'category': category,
        'fileName': file_name,
        'uploadedAt': datetime.now(timezone.utc).isoformat(),
    }
    chunks = splitter.create_documents([raw_text], metadatas=[metadata])

    # 3. 分片数量限制
    if len(chunks) > MAX_CHUNKS:
        logger.warn('rag: too many chunks, truncating', {
            'original': len(chunks), 'truncated': MAX_CHUNKS,
        })
        chunks = chunks[:MAX_CHUNKS]

    logger.info('rag: document split', {'docId': doc_id, 'chunks': len(chunks)})

    # 4. 向量化并存入向量库
    vs = await get_vector_store()
    await vs.add_documents(chunks)

    # 5. 保存文档元信息
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

    # 6. 清理临时文件
    try:
        os.unlink(file_path)
    except OSError:
        pass

    logger.info('rag: ingest complete', {'docId': doc_id, 'chunks': len(chunks)})
    return doc_meta


async def delete_document(doc_id):
    """删除文档（从注册表和向量库中移除）"""
    if doc_id not in _doc_registry:
        raise ValueError('文档不存在')

    global _vector_store
    if _vector_store:
        # 从向量库中移除该文档的所有分片
        _vector_store.vectors = [
            v for v in _vector_store.vectors
            if v['metadata'].get('docId') != doc_id
        ]

    del _doc_registry[doc_id]
    logger.info('rag: document deleted', {'docId': doc_id})
