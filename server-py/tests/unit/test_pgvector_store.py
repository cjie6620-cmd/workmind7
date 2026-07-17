"""
向量存储单元测试

测试目标：app/services/rag/pgvector_store.py
覆盖：PGVectorStore 的参数校验、绑定查询和外部事务复用
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.pgvector_store import PGVectorStore


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_should_initialize_with_correct_dimension():
    """应使用正确的向量维度初始化"""
    store = PGVectorStore(embedding_dim=1024)
    assert store.embedding_dim == 1024


def test_should_default_to_1024_dimension():
    """默认维度应为 1024"""
    store = PGVectorStore()
    assert store.embedding_dim == 1024


# ── Singleton 测试 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_vector_store_returns_singleton():
    """get_vector_store 应返回单例"""
    from app.services.rag import pgvector_store as mod

    # reset_singletons 已将 _vector_store 设为 None
    store1 = await mod.get_vector_store()
    store2 = await mod.get_vector_store()
    assert store1 is store2
    assert isinstance(store1, PGVectorStore)


@pytest.mark.parametrize(
    "vector",
    [
        [0.1, 0.2],
        [0.1, 0.2, float("nan")],
        [0.1, 0.2, "not-a-number"],
    ],
)
def test_should_reject_invalid_vector_dimension_or_values(vector):
    store = PGVectorStore(embedding_dim=3)

    with pytest.raises(ValueError):
        store._normalize_vector(vector)


@pytest.mark.asyncio
@pytest.mark.parametrize("k", [0, 101, -1, True, 1.5])
async def test_similarity_search_should_reject_invalid_k(k):
    store = PGVectorStore(embedding_dim=3)

    with pytest.raises(ValueError, match="k 必须"):
        await store.similarity_search_with_score([0.1, 0.2, 0.3], k=k)


@pytest.mark.asyncio
async def test_similarity_search_should_bind_vector_and_filters_as_parameters():
    store = PGVectorStore(embedding_dim=3)
    result = MagicMock()
    result.fetchall.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    doc_id = uuid.uuid4()

    with patch(
        "app.services.rag.pgvector_store.async_session_factory",
        return_value=_AsyncContext(session),
    ):
        rows = await store.similarity_search_with_score(
            [0.1, 0.2, 0.3],
            k=4,
            doc_id=str(doc_id),
            category="HR",
        )

    statement, params = session.execute.await_args.args
    sql = str(statement)
    assert rows == []
    assert ":query_vector" in sql
    assert "[0.1,0.2,0.3]" not in sql
    assert params["query_vector"] == [0.1, 0.2, 0.3]
    assert params["doc_id"] == doc_id
    assert params["category"] == "HR"
    assert params["k"] == 4


@pytest.mark.asyncio
async def test_add_documents_should_use_external_session_without_committing():
    store = PGVectorStore(embedding_dim=3)
    session = MagicMock()
    doc_id = uuid.uuid4()

    await store.add_documents(
        [
            {
                "doc_id": str(doc_id),
                "chunk_index": 0,
                "content": "content",
                "embedding": [0.1, 0.2, 0.3],
                "metadata": {"category": "HR"},
            }
        ],
        session=session,
    )

    chunks = session.add_all.call_args.args[0]
    assert len(chunks) == 1
    assert chunks[0].doc_id == doc_id
    assert list(chunks[0].embedding) == [0.1, 0.2, 0.3]
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_delete_should_use_external_session_without_committing():
    store = PGVectorStore(embedding_dim=3)
    session = MagicMock()
    session.execute = AsyncMock()
    doc_id = uuid.uuid4()

    await store.delete_by_doc_id(str(doc_id), session=session)

    session.execute.assert_awaited_once()
    session.commit.assert_not_called()
