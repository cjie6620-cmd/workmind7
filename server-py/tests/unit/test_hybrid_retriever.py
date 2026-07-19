"""BM25 分类缓存、并发重建和跨 worker 版本检测测试。"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _reset_bm25_cache():
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_cache.clear()
    mod._bm25_locks.clear()
    mod._bm25_retriever = None
    mod._bm25_category = None
    mod._bm25_stale = False
    yield
    mod._bm25_cache.clear()
    mod._bm25_locks.clear()


def _make_real_bm25(content="测试内容"):
    from langchain_community.retrievers import BM25Retriever

    return BM25Retriever.from_documents(
        [Document(page_content=content, metadata={})],
        k=20,
        preprocess_func=lambda value: list(value),
    )


def test_should_mark_bm25_stale_and_clear_cached_categories():
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_cache["HR"] = mod._BM25CacheEntry((1, None), object())
    mod.mark_bm25_stale()

    assert mod._bm25_stale is True
    assert mod._bm25_cache == {}


@pytest.mark.asyncio
async def test_should_fallback_to_vector_when_bm25_empty():
    from app.services.rag import hybrid_retriever as mod
    from app.services.rag.retriever import PGVectorRetriever

    with (
        patch.object(mod, "_get_chunk_version", new=AsyncMock(return_value=(0, None))),
        patch.object(mod, "_build_bm25_retriever", new=AsyncMock(return_value=None)),
    ):
        retriever = await mod.get_hybrid_retriever()

    assert isinstance(retriever, PGVectorRetriever)


@pytest.mark.asyncio
async def test_should_create_ensemble_with_correct_params():
    from app.services.rag import hybrid_retriever as mod

    bm25 = _make_real_bm25()
    with (
        patch.object(mod, "_get_cached_bm25", new=AsyncMock(return_value=bm25)),
        patch("app.services.rag.hybrid_retriever.EnsembleRetriever") as ensemble_cls,
    ):
        ensemble_cls.return_value = MagicMock()
        await mod.get_hybrid_retriever("HR")

    kwargs = ensemble_cls.call_args.kwargs
    assert kwargs["retrievers"][1] is bm25
    assert kwargs["weights"] == [0.5, 0.5]
    assert kwargs["c"] == 60


@pytest.mark.asyncio
async def test_same_category_concurrency_should_build_once():
    from app.services.rag import hybrid_retriever as mod

    built = object()
    build_count = 0

    async def build(category, owner_user_id=None):
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0)
        return built

    with (
        patch.object(mod, "_get_chunk_version", new=AsyncMock(return_value=(1, "v1"))),
        patch.object(mod, "_build_bm25_retriever", side_effect=build),
    ):
        first, second = await asyncio.gather(
            mod._get_cached_bm25("HR"),
            mod._get_cached_bm25("HR"),
        )

    assert first is built
    assert second is built
    assert build_count == 1


@pytest.mark.asyncio
async def test_different_categories_should_not_replace_each_other():
    from app.services.rag import hybrid_retriever as mod

    async def build(category, owner_user_id=None):
        await asyncio.sleep(0)
        return SimpleNamespace(category=category)

    with (
        patch.object(mod, "_get_chunk_version", new=AsyncMock(return_value=(1, "v1"))),
        patch.object(mod, "_build_bm25_retriever", side_effect=build),
    ):
        hr, finance = await asyncio.gather(
            mod._get_cached_bm25("HR"),
            mod._get_cached_bm25("财务"),
        )

    assert hr.category == "HR"
    assert finance.category == "财务"
    # 缓存键为 (category, owner_user_id) 复合键
    assert set(mod._bm25_cache) == {("HR", None), ("财务", None)}
    assert mod._bm25_cache[("HR", None)].retriever is hr
    assert mod._bm25_cache[("财务", None)].retriever is finance


@pytest.mark.asyncio
async def test_database_version_change_should_rebuild_cached_category():
    from app.services.rag import hybrid_retriever as mod

    state = {"version": (1, "v1")}
    builds = []

    async def get_version(category):
        return state["version"]

    async def build(category, owner_user_id=None):
        retriever = object()
        builds.append(retriever)
        return retriever

    with (
        patch.object(mod, "_get_chunk_version", side_effect=get_version),
        patch.object(mod, "_build_bm25_retriever", side_effect=build),
    ):
        first = await mod._get_cached_bm25("HR")
        unchanged = await mod._get_cached_bm25("HR")
        state["version"] = (2, "v2")
        changed = await mod._get_cached_bm25("HR")

    assert first is unchanged
    assert changed is not first
    assert len(builds) == 2


@pytest.mark.asyncio
async def test_chunk_version_should_bind_category_and_return_count_timestamp():
    from app.services.rag import hybrid_retriever as mod

    timestamp = datetime(2026, 1, 1)
    result = MagicMock()
    result.first.return_value = (3, timestamp)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with patch.object(
        mod,
        "async_session_factory",
        return_value=_AsyncContext(session),
    ):
        version = await mod._get_chunk_version("HR")

    statement, params = session.execute.await_args.args
    assert version == (3, timestamp)
    assert ":category" in str(statement)
    assert params == {"category": "HR"}


def test_should_tokenize_chinese_text():
    from app.services.rag.hybrid_retriever import _jieba_tokenize

    tokens = _jieba_tokenize("员工年假有多少天")
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    assert any("年假" in token for token in tokens) or any("员工" in token for token in tokens)


def test_should_handle_empty_string():
    from app.services.rag.hybrid_retriever import _jieba_tokenize

    assert isinstance(_jieba_tokenize(""), list)
