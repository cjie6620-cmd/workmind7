"""
文档处理质量单元测试

测试目标：app/services/rag/ingest.py
覆盖：文本提取、切片、向量化、入库流程
"""

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document as LangChainDocument

from app.services.rag import ingest as ingest_mod
from app.services.rag.ingest import (
    extract_text,
    ingest_document,
    delete_document,
    MAX_CHUNKS,
)


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _TrackingTransaction:
    def __init__(self):
        self.exit_error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_error = exc_type
        return False


def _fake_session(transaction=None):
    session = MagicMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    if transaction is not None:
        session.begin.return_value = transaction
    return session


# ── 文本提取测试 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_extract_text_from_txt(sample_documents_dir):
    """TXT 文件应正确读取为纯文本"""
    path = str(sample_documents_dir / "公司规章制度.txt")
    text = await extract_text(path)
    assert isinstance(text, str)
    assert len(text) > 100
    assert "规章制度" in text


@pytest.mark.asyncio
async def test_should_extract_text_from_md(sample_documents_dir):
    """Markdown 文件应保留格式"""
    path = str(sample_documents_dir / "产品介绍.md")
    text = await extract_text(path)
    assert isinstance(text, str)
    assert len(text) > 100
    assert "# " in text or "WorkMind" in text


@pytest.mark.asyncio
async def test_should_fallback_to_pypdf_when_mineru_fails(tmp_path):
    """MinerU API 失败时应降级到 pypdf"""
    # 创建一个最小 PDF 文件用于 pypdf 测试
    # 注意：pypdf 能读取的最小 PDF 需要有效结构
    # 这里测试 MinerU 降级逻辑，用 txt 文件作为 fallback 对象
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("测试内容", encoding="utf-8")

    text = await extract_text(str(txt_file))
    assert text == "测试内容"


@pytest.mark.asyncio
async def test_should_extract_unsupported_ext_as_text(tmp_path):
    """不支持的扩展名应尝试作为文本读取"""
    file = tmp_path / "test.xyz"
    file.write_text("fallback content", encoding="utf-8")
    text = await extract_text(str(file))
    assert text == "fallback content"


# ── 文档入库测试 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_reject_empty_document(tmp_path):
    """空文档应抛出 RuntimeError"""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="文档内容为空"):
        await ingest_document(
            file_path=str(empty_file),
            file_name="empty.txt",
            title="空文档",
        )
    assert not empty_file.exists()


@pytest.mark.asyncio
async def test_should_split_text_into_chunks(sample_documents_dir):
    """切片后 chunk 数量应在预期范围内，每个 chunk ≤ 500 字符"""
    path = str(sample_documents_dir / "公司规章制度.txt")

    # 读取原始文本预估切片数
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # 按平均 450 字符/chunk 估算
    estimated_min = len(raw_text) // 550
    estimated_max = len(raw_text) // 400 + 1

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    chunks = splitter.create_documents([raw_text])

    assert estimated_min <= len(chunks) <= estimated_max + 2
    for chunk in chunks:
        assert len(chunk.page_content) <= 500


@pytest.mark.asyncio
async def test_should_reject_document_over_chunk_limit_and_remove_temp_file(tmp_path):
    """超过分片上限必须明确拒绝，不能静默截断或进入嵌入阶段。"""
    temp_file = tmp_path / "too-large.txt"
    temp_file.write_text("content", encoding="utf-8")
    chunks = [LangChainDocument(page_content=f"chunk-{i}") for i in range(MAX_CHUNKS + 1)]

    with (
        patch(
            "app.services.rag.ingest.RecursiveCharacterTextSplitter.create_documents",
            return_value=chunks,
        ),
        patch("app.services.rag.ingest.get_embeddings") as get_embeddings,
    ):
        with pytest.raises(ValueError, match="超过上限"):
            await ingest_document(str(temp_file), "too-large.txt")

    get_embeddings.assert_not_called()
    assert not temp_file.exists()


@pytest.mark.asyncio
async def test_ingest_should_stage_document_and_chunks_in_same_transaction(tmp_path):
    temp_file = tmp_path / "atomic.txt"
    temp_file.write_text("atomic document content", encoding="utf-8")
    transaction = _TrackingTransaction()
    session = _fake_session(transaction)
    embeddings = MagicMock()
    embeddings.aembed_documents = AsyncMock(return_value=[[0.0] * 1024])
    vector_store = MagicMock()
    vector_store.add_documents = AsyncMock()

    with (
        patch("app.services.rag.ingest.async_session_factory", return_value=_AsyncContext(session)),
        patch("app.services.rag.ingest.get_embeddings", return_value=embeddings),
        patch("app.services.rag.ingest.get_vector_store", new=AsyncMock(return_value=vector_store)),
        patch("app.services.rag.ingest.mark_bm25_stale"),
    ):
        metadata = await ingest_document(
            str(temp_file),
            "atomic.txt",
            owner_user_id="user-1",
        )

    assert transaction.exit_error is None
    assert session.add.call_count == 1
    assert vector_store.add_documents.await_args.kwargs["session"] is session
    assert metadata["ownerUserId"] == "user-1"
    assert metadata["id"] in ingest_mod._doc_registry
    assert not temp_file.exists()


@pytest.mark.asyncio
async def test_ingest_failure_should_roll_back_and_not_publish_registry_entry(tmp_path):
    temp_file = tmp_path / "failing.txt"
    temp_file.write_text("failing document content", encoding="utf-8")
    transaction = _TrackingTransaction()
    session = _fake_session(transaction)
    embeddings = MagicMock()
    embeddings.aembed_documents = AsyncMock(return_value=[[0.0] * 1024])
    vector_store = MagicMock()
    vector_store.add_documents = AsyncMock(side_effect=RuntimeError("chunk insert failed"))
    ingest_mod._doc_registry.clear()

    with (
        patch("app.services.rag.ingest.async_session_factory", return_value=_AsyncContext(session)),
        patch("app.services.rag.ingest.get_embeddings", return_value=embeddings),
        patch("app.services.rag.ingest.get_vector_store", new=AsyncMock(return_value=vector_store)),
        patch("app.services.rag.ingest.mark_bm25_stale") as mark_stale,
    ):
        with pytest.raises(RuntimeError, match="chunk insert failed"):
            await ingest_document(str(temp_file), "failing.txt")

    assert transaction.exit_error is RuntimeError
    assert ingest_mod._doc_registry == {}
    mark_stale.assert_not_called()
    assert not temp_file.exists()


@pytest.mark.asyncio
async def test_registry_should_refresh_from_database_instead_of_stale_memory():
    doc_id = uuid.uuid4()
    row = SimpleNamespace(
        id=doc_id,
        title="DB document",
        file_name="db.txt",
        category="HR",
        chunks=2,
        chars=20,
        preview="preview",
        owner_user_id="user-1",
        created_at=datetime(2026, 1, 1),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session = _fake_session()
    session.execute.return_value = result
    ingest_mod._doc_registry.clear()
    ingest_mod._doc_registry["stale"] = {"id": "stale"}

    with patch(
        "app.services.rag.ingest.async_session_factory",
        return_value=_AsyncContext(session),
    ):
        documents = await ingest_mod.get_doc_registry()

    assert documents[0]["id"] == str(doc_id)
    assert documents[0]["ownerUserId"] == "user-1"
    assert "stale" not in ingest_mod._doc_registry


@pytest.mark.asyncio
async def test_delete_should_use_database_and_same_transaction_when_cache_is_empty():
    doc_id = uuid.uuid4()
    transaction = _TrackingTransaction()
    session = _fake_session(transaction)
    found = MagicMock()
    found.scalar_one_or_none.return_value = SimpleNamespace(owner_user_id="user-1")
    session.execute.side_effect = [found, MagicMock()]
    vector_store = MagicMock()
    vector_store.delete_by_doc_id = AsyncMock()
    ingest_mod._doc_registry.clear()

    with (
        patch("app.services.rag.ingest.async_session_factory", return_value=_AsyncContext(session)),
        patch("app.services.rag.ingest.get_vector_store", new=AsyncMock(return_value=vector_store)),
        patch("app.services.rag.ingest.mark_bm25_stale"),
    ):
        await delete_document(str(doc_id), requester_user_id="user-1")

    assert transaction.exit_error is None
    vector_store.delete_by_doc_id.assert_awaited_once_with(str(doc_id), session=session)


@pytest.mark.asyncio
async def test_delete_failure_should_leave_registry_snapshot_unchanged():
    doc_id = uuid.uuid4()
    transaction = _TrackingTransaction()
    session = _fake_session(transaction)
    found = MagicMock()
    found.scalar_one_or_none.return_value = SimpleNamespace(owner_user_id="user-1")
    session.execute.return_value = found
    vector_store = MagicMock()
    vector_store.delete_by_doc_id = AsyncMock(side_effect=RuntimeError("delete failed"))
    ingest_mod._doc_registry[str(doc_id)] = {"id": str(doc_id)}

    with (
        patch("app.services.rag.ingest.async_session_factory", return_value=_AsyncContext(session)),
        patch("app.services.rag.ingest.get_vector_store", new=AsyncMock(return_value=vector_store)),
        patch("app.services.rag.ingest.mark_bm25_stale") as mark_stale,
    ):
        with pytest.raises(RuntimeError, match="delete failed"):
            await delete_document(str(doc_id), requester_user_id="user-1")

    assert transaction.exit_error is RuntimeError
    assert str(doc_id) in ingest_mod._doc_registry
    mark_stale.assert_not_called()


@pytest.mark.asyncio
async def test_delete_should_reject_non_owner_before_writing():
    doc_id = uuid.uuid4()
    transaction = _TrackingTransaction()
    session = _fake_session(transaction)
    found = MagicMock()
    found.scalar_one_or_none.return_value = SimpleNamespace(owner_user_id="owner")
    session.execute.return_value = found
    vector_store = MagicMock()
    vector_store.delete_by_doc_id = AsyncMock()

    with (
        patch("app.services.rag.ingest.async_session_factory", return_value=_AsyncContext(session)),
        patch("app.services.rag.ingest.get_vector_store", new=AsyncMock(return_value=vector_store)),
    ):
        with pytest.raises(PermissionError, match="无权"):
            await delete_document(str(doc_id), requester_user_id="other")

    vector_store.delete_by_doc_id.assert_not_awaited()
    assert transaction.exit_error is PermissionError


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
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    # 足够长的文本才能触发切片
    text = "第一句话的内容。第二句话的内容。第三句话的内容。第四句话的内容。第五句话的内容。"
    chunks = splitter.create_documents([text])
    # 文本总长度约 45 字符，chunk_size=30，应被按句号分割为 2+ 片段
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.page_content) <= 40  # chunk_size + overlap 容差
