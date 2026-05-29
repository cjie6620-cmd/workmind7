"""
RAG 文档入库模块

文档处理流程：
1. 文件保存到本地
2. 提取文本（支持 .txt/.md/.pdf）
3. 文本分片（RecursiveCharacterTextSplitter）
4. 向量化（本地 sentence-transformers）
5. 存入 PostgreSQL + pgvector
6. 清理临时文件
7. 文档元信息持久化到 documents 表
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..model import get_embeddings
from .pgvector_store import get_vector_store
from ...core.database import async_session_factory
from ...models.entities import RagChunk, Document
from ...utils.logger import logger

# 分片上限
MAX_CHUNKS = 300

# ── 文档注册表（从数据库加载）─────────────────────────────

_doc_registry: dict = {}

async def load_doc_registry():
    """从数据库加载文档注册表"""
    from sqlalchemy import select
    async with async_session_factory() as session:
        result = await session.execute(select(Document))
        rows = result.scalars().all()

    for row in rows:
        _doc_registry[row.id] = {
            'id': row.id,
            'title': row.title,
            'fileName': row.file_name,
            'category': row.category,
            'chunks': row.chunks,
            'chars': row.chars,
            'preview': row.preview,
            'uploadedAt': row.created_at.isoformat() if row.created_at else None,
        }


def get_doc_registry():
    """获取所有文档元信息"""
    return list(_doc_registry.values())


def get_doc(doc_id):
    """获取指定文档元信息"""
    return _doc_registry.get(doc_id)


# ── 文本提取 ────────────────────────────────────────────────

def _extract_pdf_by_pypdf(file_path):
    """使用 pypdf 提取 PDF 文本（fallback 方案）"""
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


async def _extract_pdf_by_mineru(file_path):
    """通过 MinerU v4 精准解析 API 提取 PDF 文本，失败时 fallback 到 pypdf"""
    import io
    import time
    import zipfile

    import requests

    from ...config import config

    mc = config.get('mineru', {})
    api_key = mc.get('api_key', '')
    timeout = mc.get('timeout', 120)
    model_version = mc.get('model_version', 'vlm')

    if not api_key:
        logger.warn('mineru: api_key 未配置，fallback 到 pypdf')
        return _extract_pdf_by_pypdf(file_path)

    base_url = 'https://mineru.net'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }

    def _sync():
        file_name = os.path.basename(file_path)

        # Step 1: 申请签名上传 URL
        resp = requests.post(
            f'{base_url}/api/v4/file-urls/batch',
            headers=headers,
            json={
                'files': [{'name': file_name}],
                'model_version': model_version,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 0:
            raise RuntimeError(f"申请上传URL失败: {data.get('msg')}")

        batch_id = data['data']['batch_id']
        file_urls = data['data']['file_urls']

        # Step 2: PUT 上传文件到签名 URL
        with open(file_path, 'rb') as f:
            upload_resp = requests.put(file_urls[0], data=f)
            upload_resp.raise_for_status()

        # Step 3: 轮询解析结果
        start = time.time()
        poll_interval = 5
        while time.time() - start < timeout:
            poll_resp = requests.get(
                f'{base_url}/api/v4/extract-results/batch/{batch_id}',
                headers=headers,
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            if poll_data.get('code') != 0:
                raise RuntimeError(f"查询解析结果失败: {poll_data.get('msg')}")

            results = poll_data['data']['extract_result']
            item = results[0]
            state = item['state']

            if state == 'done':
                # Step 4: 下载 zip，提取 full.md
                zip_url = item['full_zip_url']
                zip_resp = requests.get(zip_url)
                zip_resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
                    for name in zf.namelist():
                        if name.endswith('full.md'):
                            return zf.read(name).decode('utf-8')
                raise RuntimeError('zip 中未找到 full.md')

            if state == 'failed':
                raise RuntimeError(f"解析失败: {item.get('err_msg', '未知错误')}")

            time.sleep(poll_interval)

        raise RuntimeError(f'轮询超时 ({timeout}s)')

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
    doc_id = str(uuid.uuid4())
    logger.info('rag: ingesting document', {'docId': doc_id, 'title': title, 'category': category})

    # 1. 提取文本
    raw_text = await extract_text(file_path)
    if not raw_text.strip():
        raise RuntimeError('文档内容为空，无法处理')

    # 2. 文本分片
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
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

    # 4. 向量化并批量入库 PostgreSQL + pgvector
    texts = [d.page_content for d in chunks]
    BATCH = 5
    documents_to_insert = []

    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        batch_docs = chunks[i:i + BATCH]
        vecs = await get_embeddings().aembed_documents(batch)

        for j, vec in enumerate(vecs):
            documents_to_insert.append({
                'doc_id': doc_id,
                'chunk_index': i + j,
                'content': batch[j],
                'embedding': vec,
                'metadata': batch_docs[j].metadata,
            })

        logger.info('rag: embedding progress', {
            'done': min(i + BATCH, len(texts)),
            'total': len(texts),
        })

    # 5. 存入 pgvector
    vs = await get_vector_store()
    await vs.add_documents(documents_to_insert)

    # 6. 保存文档元信息到数据库
    doc_meta = {
        'id': doc_id,
        'title': title or file_name,
        'fileName': file_name,
        'category': category,
        'chunks': len(chunks),
        'chars': len(raw_text),
        'preview': raw_text[:120].replace('\n', ' ') + '...',
        'uploadedAt': datetime.now(timezone.utc).isoformat(),
    }

    # 保存到 documents 表
    async with async_session_factory() as session:
        doc = Document(
            id=doc_id,
            title=title or file_name,
            file_name=file_name,
            category=category,
            chunks=len(chunks),
            chars=len(raw_text),
            preview=raw_text[:200].replace('\n', ' ') + '...',
        )
        session.add(doc)
        await session.commit()

    _doc_registry[doc_id] = doc_meta

    # 7. 清理临时文件
    try:
        os.unlink(file_path)
    except OSError:
        pass

    logger.info('rag: ingest complete', {'docId': doc_id, 'chunks': len(chunks)})
    return doc_meta


async def delete_document(doc_id):
    """删除文档（从 pgvector 和数据库中移除）"""
    if doc_id not in _doc_registry:
        raise ValueError('文档不存在')

    vs = await get_vector_store()
    await vs.delete_by_doc_id(doc_id)

    # 从 documents 表删除
    from sqlalchemy import delete
    async with async_session_factory() as session:
        await session.execute(delete(Document).where(Document.id == doc_id))
        await session.commit()

    del _doc_registry[doc_id]
    logger.info('rag: document deleted', {'docId': doc_id})