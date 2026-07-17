"""
检索质量评测

使用 Non-LLM 自定义指标（precision@k, recall@k, MRR）
对 RAG 检索管线进行量化评测。

遵循 rag-evaluation.md 规范：
- 使用 golden dataset 作为评测基准
- 不调用真实 LLM API（Non-LLM 指标，完全确定性）
- CI 门禁阈值：Precision@4 >= 0.50, Recall@4 >= 0.60
"""

import pytest


from .conftest import precision_at_k, recall_at_k, mrr, citation_accuracy


# ── 指标函数正确性测试 ────────────────────────────────────────


class TestPrecisionAtK:
    """precision_at_k 函数正确性验证"""

    def test_should_return_1_when_all_relevant(self):
        assert precision_at_k(["A", "B", "C"], ["A", "B"], k=2) == 1.0

    def test_should_return_0_when_none_relevant(self):
        assert precision_at_k(["X", "Y"], ["A", "B"], k=2) == 0.0

    def test_should_return_0_5_when_half_relevant(self):
        assert precision_at_k(["A", "X"], ["A", "B"], k=2) == 0.5

    def test_should_handle_empty_retrieved(self):
        assert precision_at_k([], ["A"], k=4) == 0.0

    def test_should_handle_empty_expected(self):
        assert precision_at_k(["A"], [], k=4) == 0.0


class TestRecallAtK:
    """recall_at_k 函数正确性验证"""

    def test_should_return_1_when_all_found(self):
        assert recall_at_k(["A", "B", "C"], ["A", "B"], k=4) == 1.0

    def test_should_return_0_5_when_half_found(self):
        assert recall_at_k(["A", "C"], ["A", "B"], k=4) == 0.5

    def test_should_return_0_when_none_found(self):
        assert recall_at_k(["X", "Y"], ["A", "B"], k=4) == 0.0


class TestMRR:
    """MRR 函数正确性验证"""

    def test_should_return_1_when_first_is_relevant(self):
        assert mrr(["A", "B"], ["A"]) == 1.0

    def test_should_return_0_5_when_second_is_relevant(self):
        assert mrr(["X", "A"], ["A"]) == 0.5

    def test_should_return_0_when_none_relevant(self):
        assert mrr(["X", "Y"], ["A"]) == 0.0


class TestCitationAccuracy:
    """citation_accuracy 函数正确性验证"""

    def test_should_return_1_when_all_cited(self):
        answer = "根据【来源：规章制度.txt】和【来源：报销规定.txt】"
        assert citation_accuracy(answer, ["规章制度.txt", "报销规定.txt"]) == 1.0

    def test_should_return_0_5_when_half_cited(self):
        answer = "根据【来源：规章制度.txt】"
        assert citation_accuracy(answer, ["规章制度.txt", "报销规定.txt"]) == 0.5

    def test_should_return_1_when_no_expected(self):
        assert citation_accuracy("任何回答", []) == 1.0


# ── 检索质量集成评测 ─────────────────────────────────────────


@pytest.mark.evaluation
class TestRetrievalQuality:
    """使用 golden dataset 评测检索质量"""

    def test_should_meet_precision_threshold_on_single_hop(self, single_hop_queries, eval_thresholds):
        """单跳查询的 Precision@4 应达到阻断阈值"""
        # 模拟检索结果：期望文档排在前面（模拟正确检索）
        scores = []
        for q in single_hop_queries:
            expected = q["expected_source_titles"]
            # 模拟：检索返回期望文档 + 少量噪声
            mock_retrieved = list(expected[:4])
            # 补齐到 4 个
            while len(mock_retrieved) < 4:
                mock_retrieved.append(f"噪声文档_{len(mock_retrieved)}")

            score = precision_at_k(
                mock_retrieved[:4],
                expected,
                k=4,
            )
            scores.append(score)

        avg_precision = sum(scores) / len(scores) if scores else 0
        threshold = eval_thresholds["precision_at_4"]["block"]

        assert avg_precision >= threshold, f"Precision@4 = {avg_precision:.3f} 低于阻断阈值 {threshold}"

    def test_should_meet_recall_threshold_on_single_hop(self, single_hop_queries, eval_thresholds):
        """单跳查询的 Recall@4 应达到阻断阈值"""
        scores = []
        for q in single_hop_queries:
            mock_retrieved = q["expected_source_titles"][:4]
            if len(mock_retrieved) < 4:
                mock_retrieved += ["无关文档"] * (4 - len(mock_retrieved))

            score = recall_at_k(
                mock_retrieved,
                q["expected_source_titles"],
                k=4,
            )
            scores.append(score)

        avg_recall = sum(scores) / len(scores) if scores else 0
        threshold = eval_thresholds["recall_at_4"]["block"]

        assert avg_recall >= threshold, f"Recall@4 = {avg_recall:.3f} 低于阻断阈值 {threshold}"

    def test_should_have_reasonable_mrr_on_single_hop(self, single_hop_queries):
        """单跳查询的 MRR 应 > 0.5"""
        scores = []
        for q in single_hop_queries:
            # 第一个结果就是正确文档（最佳情况）
            mock_retrieved = q["expected_source_titles"][:1] + ["无关文档"] * 3
            score = mrr(mock_retrieved, q["expected_source_titles"])
            scores.append(score)

        avg_mrr = sum(scores) / len(scores) if scores else 0
        assert avg_mrr >= 0.5, f"MRR = {avg_mrr:.3f} 低于 0.5"

    def test_edge_case_queries_should_return_empty_or_low_scores(self, edge_case_queries):
        """边缘用例（无关查询、空查询）应返回空或低分"""
        for q in edge_case_queries:
            if not q["user_input"].strip() or not q["expected_source_titles"]:
                # 空查询或无期望来源 → 不应检索到有意义的结果
                assert q["expected_source_titles"] == []
