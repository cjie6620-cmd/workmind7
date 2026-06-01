"""
混合检索单元测试

测试目标：app/services/rag/hybrid_retriever.py
覆盖：BM25 构建、向量检索、RRF 融合、分类过滤、降级逻辑
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.documents import Document


# ── BM25 相关测试 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_mark_bm25_stale():
    """mark_bm25_stale 应将 stale 标记设为 True"""
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_stale = False
    mod.mark_bm25_stale()
    assert mod._bm25_stale is True


@pytest.mark.asyncio
async def test_should_fallback_to_vector_when_bm25_empty():
    """BM25 索引为空时应返回纯向量检索器"""
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_retriever = None
    mod._bm25_stale = False
    mod._bm25_category = None

    with patch.object(mod, '_build_bm25_retriever', new_callable=AsyncMock):
        mod._bm25_retriever = None
        mod._bm25_stale = False

        retriever = await mod.get_hybrid_retriever()

        from app.services.rag.retriever import PGVectorRetriever
        assert isinstance(retriever, PGVectorRetriever)


# ── 检索器构造测试 ─────────────────────────────────────────────

def _make_real_bm25():
    """创建一个真实 BM25Retriever（最小数据），可过 EnsembleRetriever 的 Runnable 校验"""
    from langchain_community.retrievers import BM25Retriever
    return BM25Retriever.from_documents(
        [Document(page_content="测试内容", metadata={})],
        k=20,
        preprocess_func=lambda x: list(x),
    )


@pytest.mark.asyncio
async def test_should_create_ensemble_with_correct_params():
    """混合检索器应使用正确的 RRF 参数"""
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_stale = False
    mod._bm25_category = None
    mod._bm25_retriever = _make_real_bm25()

    with patch.object(mod, '_build_bm25_retriever', new_callable=AsyncMock), \
         patch('app.services.rag.hybrid_retriever.EnsembleRetriever') as MockEnsemble:
        mock_instance = MagicMock()
        mock_instance.weights = [0.5, 0.5]
        mock_instance.c = 60
        MockEnsemble.return_value = mock_instance

        await mod.get_hybrid_retriever()

        MockEnsemble.assert_called_once()
        call_kwargs = MockEnsemble.call_args[1]
        assert call_kwargs['weights'] == [0.5, 0.5]
        assert call_kwargs['c'] == 60


@pytest.mark.asyncio
async def test_should_rebuild_bm25_when_stale():
    """stale 标记为 True 时应触发 BM25 重建"""
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_stale = True
    mod._bm25_retriever = _make_real_bm25()

    with patch.object(mod, '_build_bm25_retriever', new_callable=AsyncMock) as mock_build, \
         patch('app.services.rag.hybrid_retriever.EnsembleRetriever', return_value=MagicMock()):
        await mod.get_hybrid_retriever()
        mock_build.assert_called_once()


@pytest.mark.asyncio
async def test_should_rebuild_bm25_when_category_changes():
    """分类变更时应重建 BM25"""
    from app.services.rag import hybrid_retriever as mod

    mod._bm25_retriever = _make_real_bm25()
    mod._bm25_stale = False
    mod._bm25_category = 'HR制度'

    with patch.object(mod, '_build_bm25_retriever', new_callable=AsyncMock) as mock_build, \
         patch('app.services.rag.hybrid_retriever.EnsembleRetriever', return_value=MagicMock()):
        await mod.get_hybrid_retriever(category='财务')
        mock_build.assert_called_once_with('财务')


# ── jieba 分词测试 ─────────────────────────────────────────────

def test_should_tokenize_chinese_text():
    """jieba 分词应能正确处理中文"""
    from app.services.rag.hybrid_retriever import _jieba_tokenize

    tokens = _jieba_tokenize("员工年假有多少天")
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    assert any('年假' in t for t in tokens) or any('员工' in t for t in tokens)


def test_should_handle_empty_string():
    """空字符串分词应返回空列表或只含空字符串"""
    from app.services.rag.hybrid_retriever import _jieba_tokenize

    tokens = _jieba_tokenize("")
    assert isinstance(tokens, list)
