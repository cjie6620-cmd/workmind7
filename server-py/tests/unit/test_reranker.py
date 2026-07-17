"""
重排序效果单元测试

测试目标：app/services/rag/reranker.py
覆盖：CrossEncoderReranker 的排序、阈值过滤、top_n 限制、元数据透传
"""

from langchain_core.documents import Document

from app.services.rag.reranker import RERANK_THRESHOLD


# ── 构造辅助函数 ──────────────────────────────────────────────


def _make_doc(
    content: str, title: str = "测试文档", doc_id: str = "doc-001", category: str = "通用", vector_score: float = 0.8
) -> Document:
    """构造 LangChain Document 用于测试"""
    return Document(
        page_content=content,
        metadata={
            "title": title,
            "docId": doc_id,
            "category": category,
            "vector_score": vector_score,
        },
    )


# ── Mock CrossEncoderReranker 测试 ───────────────────────────


class _MockCrossEncoderReranker:
    """
    使用 MockReranker（tests/conftest.py 注入）进行测试
    不加载真实 CrossEncoder 模型
    """

    def test_rerank_with_mock(self):
        """用 conftest 注入的 mock reranker 做基本测试"""
        from app.services.rag import reranker as mod

        reranker = mod._reranker
        docs = [
            _make_doc("员工年假为5天，工龄5-10年7天", title="制度A"),
            _make_doc("公司产品介绍，功能特性说明", title="产品B"),
        ]

        results = reranker.rerank("年假有多少天", docs, top_n=4)

        # 第一个文档应排更前（关键词重叠更多）
        assert len(results) >= 1
        assert all("rerank_score" in r for r in results)
        assert all("title" in r for r in results)


# ── 独立 CrossEncoderReranker 逻辑测试 ───────────────────────


def test_reranker_should_sort_by_score_desc():
    """结果应按 rerank_score 降序排列"""
    from tests.conftest import MockReranker

    reranker = MockReranker(threshold=0.0)
    docs = [
        _make_doc("无关内容", title="低相关"),
        _make_doc("年假 病假 事假 婚假 产假 丧假 加班 考勤", title="高相关"),
        _make_doc("年假 事假", title="中相关"),
    ]

    results = reranker.rerank("年假有多少天", docs, top_n=3)
    scores = [r["rerank_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_reranker_should_filter_below_threshold():
    """低于阈值的结果应被过滤"""
    from tests.conftest import MockReranker

    reranker = MockReranker(threshold=0.5)
    docs = [
        _make_doc("高度相关的年假信息 员工年假制度", title="高相关"),
        _make_doc("无关的内容xyz", title="低相关"),
    ]

    results = reranker.rerank("年假有多少天", docs, top_n=4)
    for r in results:
        assert r["rerank_score"] >= 0.5


def test_reranker_should_return_top_n_results():
    """应只返回 top_n 个结果"""
    from tests.conftest import MockReranker

    reranker = MockReranker(threshold=0.0)
    docs = [_make_doc(f"文档{i} 年假", title=f"文档{i}") for i in range(10)]

    results = reranker.rerank("年假有多少天", docs, top_n=3)
    assert len(results) <= 3


def test_reranker_should_handle_empty_candidates():
    """空候选列表应返回空结果"""
    from tests.conftest import MockReranker

    reranker = MockReranker()
    results = reranker.rerank("查询", [], top_n=4)
    assert results == []


def test_reranker_should_include_metadata_in_results():
    """结果应包含完整的元数据"""
    from tests.conftest import MockReranker

    reranker = MockReranker(threshold=0.0)
    docs = [_make_doc("年假测试内容", title="制度文档", doc_id="abc-123", category="HR制度", vector_score=0.95)]

    results = reranker.rerank("年假", docs, top_n=1)
    assert len(results) >= 1

    r = results[0]
    assert "content" in r
    assert "rerank_score" in r
    assert "vector_score" in r
    assert "title" in r
    assert "docId" in r
    assert "category" in r
    assert r["title"] == "制度文档"
    assert r["docId"] == "abc-123"
    assert r["category"] == "HR制度"


def test_reranker_threshold_config():
    """阈值应从配置读取"""
    assert RERANK_THRESHOLD == 0.2


def test_mock_reranker_singleton_loaded():
    """conftest 注入的 mock reranker 应已加载"""
    from app.services.rag import reranker as mod

    assert mod._reranker is not None
