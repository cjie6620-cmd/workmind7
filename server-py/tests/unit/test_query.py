"""
RAG 生成逻辑单元测试

测试目标：app/services/rag/query.py
覆盖：retrieve_docs 调度、rag_query_stream 流式生成
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.documents import Document


# ── retrieve_docs 测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_docs_should_call_hybrid_retriever():
    """retrieve_docs 应调用混合检索器"""
    from app.services.rag.query import retrieve_docs

    mock_doc = Document(
        page_content="员工年假5天",
        metadata={"title": "制度", "docId": "d1", "category": "HR", "vector_score": 0.9},
    )

    mock_retriever = AsyncMock()
    mock_retriever.ainvoke = AsyncMock(return_value=[mock_doc])

    mock_reranker = MagicMock()
    mock_reranker.rerank = MagicMock(
        return_value=[
            {
                "content": "员工年假5天",
                "rerank_score": 0.95,
                "vector_score": 0.9,
                "title": "制度",
                "docId": "d1",
                "category": "HR",
                "preview": "员工年假5天",
            }
        ]
    )

    with (
        patch("app.services.rag.query.get_hybrid_retriever", return_value=mock_retriever),
        patch("app.services.rag.query.get_reranker", return_value=mock_reranker),
    ):
        results = await retrieve_docs("年假多少天")

    assert len(results) == 1
    assert results[0]["title"] == "制度"
    mock_retriever.ainvoke.assert_called_once_with("年假多少天")


@pytest.mark.asyncio
async def test_retrieve_docs_should_return_empty_when_no_candidates():
    """无候选结果时应返回空列表"""
    from app.services.rag.query import retrieve_docs

    mock_retriever = AsyncMock()
    mock_retriever.ainvoke = AsyncMock(return_value=[])

    with patch("app.services.rag.query.get_hybrid_retriever", return_value=mock_retriever):
        results = await retrieve_docs("不相关查询")

    assert results == []


@pytest.mark.asyncio
async def test_retrieve_docs_should_use_custom_k():
    """应支持自定义返回数量 k"""
    from app.services.rag.query import retrieve_docs

    mock_doc = Document(page_content="内容", metadata={"title": "t", "vector_score": 0.5})
    mock_retriever = AsyncMock()
    mock_retriever.ainvoke = AsyncMock(return_value=[mock_doc])

    mock_reranker = MagicMock()
    mock_reranker.rerank = MagicMock(
        return_value=[
            {
                "content": "内容",
                "rerank_score": 0.8,
                "vector_score": 0.5,
                "title": "t",
                "docId": None,
                "category": None,
                "preview": "内容",
            }
        ]
    )

    with (
        patch("app.services.rag.query.get_hybrid_retriever", return_value=mock_retriever),
        patch("app.services.rag.query.get_reranker", return_value=mock_reranker),
    ):
        await retrieve_docs("查询", k=2)

    mock_reranker.rerank.assert_called_once()
    # 验证 top_n 参数
    call_kwargs = mock_reranker.rerank.call_args
    assert call_kwargs[1]["top_n"] == 2


# ── rag_query_stream 测试 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_rag_query_stream_should_return_sources_and_stream():
    """rag_query_stream 应返回 sources 和 stream_answer"""
    from app.services.rag.query import rag_query_stream

    mock_docs = [
        {
            "content": "年假5天",
            "rerank_score": 0.9,
            "title": "制度",
            "docId": "d1",
            "category": "HR",
        }
    ]

    with patch("app.services.rag.query.retrieve_docs", return_value=mock_docs):
        result = await rag_query_stream("年假多少天")

    assert "sources" in result
    assert "stream_answer" in result
    assert result["sources"] == mock_docs


@pytest.mark.asyncio
async def test_rag_query_stream_should_yield_no_content_message_when_empty():
    """无检索结果时 stream_answer 应返回未找到提示"""
    from app.services.rag.query import rag_query_stream

    with patch("app.services.rag.query.retrieve_docs", return_value=[]):
        result = await rag_query_stream("无关查询")

    chunks = []
    async for chunk in result["stream_answer"]():
        chunks.append(chunk)

    assert len(chunks) > 0
    full_text = "".join(chunks)
    assert "未找到" in full_text or "知识库" in full_text


@pytest.mark.asyncio
async def test_rag_query_stream_should_stream_answer():
    """有检索结果时 stream_answer 应流式返回回答"""
    from app.services.rag.query import rag_query_stream

    mock_docs = [
        {
            "content": "年假5天",
            "rerank_score": 0.9,
            "title": "制度",
            "docId": "d1",
            "category": "HR",
        }
    ]

    # Mock chat model 的 astream 方法
    mock_model = MagicMock()

    async def mock_astream(inputs):
        for char in "年假5天":
            chunk = MagicMock()
            chunk.content = char
            yield chunk

    # 模拟 prompt | model 的 chain 行为
    mock_prompt = MagicMock()
    chain = MagicMock()
    chain.astream = mock_astream
    mock_prompt.__or__ = MagicMock(return_value=chain)

    with (
        patch("app.services.rag.query.retrieve_docs", return_value=mock_docs),
        patch("app.services.rag.query.ChatPromptTemplate") as mock_template,
        patch("app.services.rag.query.get_chat_model", return_value=mock_model),
    ):
        mock_template.from_messages.return_value = mock_prompt

        result = await rag_query_stream("年假多少天")
        chunks = []
        async for chunk in result["stream_answer"]():
            chunks.append(chunk)

    assert len(chunks) > 0
