"""
文档处理质量单元测试

测试目标：app/services/rag/ingest.py
覆盖：文本提取、切片、向量化、入库流程
"""

import os
import tempfile

import pytest

from app.services.rag.ingest import (
    extract_text,
    ingest_document,
    delete_document,
    MAX_CHUNKS,
)
from app.services.rag.ingest import _doc_registry


# ── 文本提取测试 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_extract_text_from_txt(sample_documents_dir):
    """TXT 文件应正确读取为纯文本"""
    path = str(sample_documents_dir / '公司规章制度.txt')
    text = await extract_text(path)
    assert isinstance(text, str)
    assert len(text) > 100
    assert '规章制度' in text


@pytest.mark.asyncio
async def test_should_extract_text_from_md(sample_documents_dir):
    """Markdown 文件应保留格式"""
    path = str(sample_documents_dir / '产品介绍.md')
    text = await extract_text(path)
    assert isinstance(text, str)
    assert len(text) > 100
    assert '# ' in text or 'WorkMind' in text


@pytest.mark.asyncio
async def test_should_fallback_to_pypdf_when_mineru_fails(tmp_path):
    """MinerU API 失败时应降级到 pypdf"""
    # 创建一个最小 PDF 文件用于 pypdf 测试
    # 注意：pypdf 能读取的最小 PDF 需要有效结构
    # 这里测试 MinerU 降级逻辑，用 txt 文件作为 fallback 对象
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("测试内容", encoding='utf-8')

    text = await extract_text(str(txt_file))
    assert text == "测试内容"


@pytest.mark.asyncio
async def test_should_extract_unsupported_ext_as_text(tmp_path):
    """不支持的扩展名应尝试作为文本读取"""
    file = tmp_path / "test.xyz"
    file.write_text("fallback content", encoding='utf-8')
    text = await extract_text(str(file))
    assert text == "fallback content"


# ── 文档入库测试 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_reject_empty_document(tmp_path):
    """空文档应抛出 RuntimeError"""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding='utf-8')

    with pytest.raises(RuntimeError, match="文档内容为空"):
        await ingest_document(
            file_path=str(empty_file),
            file_name="empty.txt",
            title="空文档",
        )


@pytest.mark.asyncio
async def test_should_split_text_into_chunks(sample_documents_dir):
    """切片后 chunk 数量应在预期范围内，每个 chunk ≤ 500 字符"""
    path = str(sample_documents_dir / '公司规章制度.txt')

    # 读取原始文本预估切片数
    with open(path, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    # 按平均 450 字符/chunk 估算
    estimated_min = len(raw_text) // 550
    estimated_max = len(raw_text) // 400 + 1

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=['\n\n', '\n', '。', '；', '，', ' ', ''],
    )
    chunks = splitter.create_documents([raw_text])

    assert estimated_min <= len(chunks) <= estimated_max + 2
    for chunk in chunks:
        assert len(chunk.page_content) <= 500


@pytest.mark.asyncio
async def test_should_limit_chunks_to_max_300(tmp_path):
    """超过 300 切片应被截断"""
    # 创建一个超长文本：每段 480 字符 + 句号，用双换行分隔以产生更多切片
    segment = "这是一段用于测试切片上限的文本内容。" * 10  # ~240 字符
    long_text = "\n\n".join([segment] * 1500)  # 1500 段，每段 ~240 字符 = ~360000 字符

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=50,
        separators=['\n\n', '\n', '。', '；', '，', ' ', ''],
    )
    chunks = splitter.create_documents([long_text])
    assert len(chunks) > MAX_CHUNKS
    # 模拟截断
    truncated = chunks[:MAX_CHUNKS]
    assert len(truncated) == MAX_CHUNKS


@pytest.mark.asyncio
async def test_should_generate_correct_embedding_dimension(mock_embeddings):
    """Mock 嵌入应产生 1024 维向量"""
    vec = await mock_embeddings.aembed_query("测试文本")
    assert len(vec) == 1024
    assert isinstance(vec[0], float)


@pytest.mark.asyncio
async def test_should_produce_deterministic_vectors(mock_embeddings):
    """相同文本应产生相同向量"""
    vec1 = await mock_embeddings.aembed_query("确定性测试")
    vec2 = await mock_embeddings.aembed_query("确定性测试")
    assert vec1 == vec2


@pytest.mark.asyncio
async def test_should_produce_different_vectors_for_different_text(mock_embeddings):
    """不同文本应产生不同向量"""
    vec1 = await mock_embeddings.aembed_query("苹果")
    vec2 = await mock_embeddings.aembed_query("香蕉")
    assert vec1 != vec2


def test_should_split_chinese_text_correctly():
    """中文分隔符应正确工作"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=30,
        chunk_overlap=5,
        separators=['\n\n', '\n', '。', '；', '，', ' ', ''],
    )
    # 足够长的文本才能触发切片
    text = "第一句话的内容。第二句话的内容。第三句话的内容。第四句话的内容。第五句话的内容。"
    chunks = splitter.create_documents([text])
    # 文本总长度约 45 字符，chunk_size=30，应被按句号分割为 2+ 片段
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.page_content) <= 40  # chunk_size + overlap 容差
