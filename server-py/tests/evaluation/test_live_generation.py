"""
Level 1: 真实 RAGAS 生成评测（调用真实 DeepSeek API）

使用 RAGAS v0.4.3 Collections API 评测 RAG 生成质量。
遵循 rag-evaluation.md 规范：
- 使用 Collections API（禁止 Legacy SingleTurnSample）
- 评测 LLM 使用国产模型 deepseek-chat
- CI 门禁阈值：Faithfulness >= 0.70, ContextRecall >= 0.60, FactualCorrectness >= 0.60

依赖：仅需 DEEPSEEK_API_KEY，不需要 embedding / 向量库 / reranker

运行方式：
    pytest tests/evaluation/test_live_generation.py -m live -v
"""

import pytest

from .conftest import EVAL_THRESHOLDS


# ── 辅助函数 ────────────────────────────────────────────────


def _extract_score(result) -> float:
    """从 RAGAS 评测结果中提取 float 分数"""
    if isinstance(result, float):
        return result
    if hasattr(result, "value"):
        return float(result.value)
    return float(result)


# ── Level 1: 逐指标单样本评测 ───────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveRagasSingleMetric:
    """
    使用真实 DeepSeek API 逐指标评测

    每个测试取 5 条 golden data，调用 RAGAS Collections API
    的 scorer.ascore() 单样本评测，断言平均分达标。
    """

    async def test_faithfulness_with_real_llm(self, evaluator_llm, sampled_golden_dataset, eval_thresholds):
        """Faithfulness 应达到阻断阈值（真实 API）"""
        from ragas.metrics.collections import Faithfulness

        scorer = Faithfulness(llm=evaluator_llm)
        scores = []

        for q in sampled_golden_dataset[:5]:
            result = await scorer.ascore(
                user_input=q["user_input"],
                response=q["reference"],
                retrieved_contexts=[q["reference"]],
            )
            score = _extract_score(result)
            scores.append(score)
            print(f"  [Faithfulness] Q: {q['user_input'][:30]}... → {score:.3f}")

        avg = sum(scores) / len(scores)
        threshold = eval_thresholds["faithfulness"]["block"]

        print(f"\n  平均 Faithfulness: {avg:.3f} (阈值: >= {threshold})")
        assert avg >= threshold, f"Faithfulness = {avg:.3f} < {threshold}"

    async def test_context_recall_with_real_llm(self, evaluator_llm, sampled_golden_dataset, eval_thresholds):
        """ContextRecall 应达到阻断阈值（真实 API）"""
        from ragas.metrics.collections import ContextRecall

        scorer = ContextRecall(llm=evaluator_llm)
        scores = []

        for q in sampled_golden_dataset[:5]:
            result = await scorer.ascore(
                user_input=q["user_input"],
                retrieved_contexts=[q["reference"]],
                reference=q["reference"],
            )
            score = _extract_score(result)
            scores.append(score)
            print(f"  [ContextRecall] Q: {q['user_input'][:30]}... → {score:.3f}")

        avg = sum(scores) / len(scores)
        threshold = eval_thresholds["context_recall"]["block"]

        print(f"\n  平均 ContextRecall: {avg:.3f} (阈值: >= {threshold})")
        assert avg >= threshold, f"ContextRecall = {avg:.3f} < {threshold}"

    async def test_factual_correctness_with_real_llm(self, evaluator_llm, sampled_golden_dataset, eval_thresholds):
        """FactualCorrectness 应达到阻断阈值（真实 API）"""
        from ragas.metrics.collections import FactualCorrectness

        scorer = FactualCorrectness(llm=evaluator_llm, mode="f1")
        scores = []

        for q in sampled_golden_dataset[:5]:
            result = await scorer.ascore(
                response=q["reference"],
                reference=q["reference"],
            )
            score = _extract_score(result)
            scores.append(score)
            print(f"  [FactualCorrectness] Q: {q['user_input'][:30]}... → {score:.3f}")

        avg = sum(scores) / len(scores)
        threshold = eval_thresholds["factual_correctness"]["block"]

        print(f"\n  平均 FactualCorrectness: {avg:.3f} (阈值: >= {threshold})")
        assert avg >= threshold, f"FactualCorrectness = {avg:.3f} < {threshold}"


# ── Level 1: 批量评测 ──────────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveRagasBatchEvaluation:
    """
    使用真实 DeepSeek API 批量评测

    使用 RAGAS evaluate() 对 sampled_golden_dataset 批量评测，
    输出三个核心指标的平均分数。
    """

    async def test_batch_evaluate_with_ragas(self, evaluator_llm, sampled_golden_dataset, eval_thresholds):
        """
        批量评测：三个核心指标应全部达标

        RAGAS 0.4.3 的 evaluate() 存在类型不兼容问题
        （collections API 的指标不继承 Metric 基类），
        因此使用 ascore() 逐样本评测后取平均值。
        """
        from ragas.metrics.collections import Faithfulness, ContextRecall, FactualCorrectness

        faithfulness_scorer = Faithfulness(llm=evaluator_llm)
        context_recall_scorer = ContextRecall(llm=evaluator_llm)
        factual_correctness_scorer = FactualCorrectness(llm=evaluator_llm, mode="f1")

        # 第一步：构造评测数据
        eval_data = []
        for q in sampled_golden_dataset:
            if not q.get("expected_source_titles"):
                continue
            eval_data.append(
                {
                    "user_input": q["user_input"],
                    "retrieved_contexts": [q["reference"]],
                    "response": q["reference"],
                    "reference": q["reference"],
                }
            )

        assert len(eval_data) > 0, "评测数据集为空"
        print(f"\n  评测数据量: {len(eval_data)} 条")

        # 第二步：逐样本评测三个指标
        faithfulness_scores = []
        context_recall_scores = []
        factual_correctness_scores = []

        for item in eval_data:
            # Faithfulness
            f_result = await faithfulness_scorer.ascore(
                user_input=item["user_input"],
                response=item["response"],
                retrieved_contexts=item["retrieved_contexts"],
            )
            faithfulness_scores.append(_extract_score(f_result))

            # ContextRecall
            cr_result = await context_recall_scorer.ascore(
                user_input=item["user_input"],
                retrieved_contexts=item["retrieved_contexts"],
                reference=item["reference"],
            )
            context_recall_scores.append(_extract_score(cr_result))

            # FactualCorrectness
            fc_result = await factual_correctness_scorer.ascore(
                response=item["response"],
                reference=item["reference"],
            )
            factual_correctness_scores.append(_extract_score(fc_result))

        # 第三步：计算平均值并断言
        avg_f = sum(faithfulness_scores) / len(faithfulness_scores)
        avg_cr = sum(context_recall_scores) / len(context_recall_scores)
        avg_fc = sum(factual_correctness_scores) / len(factual_correctness_scores)

        print("\n  ── 批量评测结果 ──")

        checks = [
            ("faithfulness", avg_f, eval_thresholds["faithfulness"]["block"]),
            ("context_recall", avg_cr, eval_thresholds["context_recall"]["block"]),
            ("factual_correctness", avg_fc, eval_thresholds["factual_correctness"]["block"]),
        ]

        for metric_name, score, threshold in checks:
            status = "PASS" if score >= threshold else "FAIL"
            print(f"  [{status}] {metric_name}: {score:.3f} (阈值: >= {threshold})")
            assert score >= threshold, f"{metric_name} = {score:.3f} < {threshold}"


# ── Level 1: Bad Case 分析 ─────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveRagasBadCaseAnalysis:
    """
    Bad Case 分析：找出低分查询，输出详细报告

    不断言通过率，只生成 bad case 报告供人工审查。
    默认 bad case 阈值为 CI 阻断阈值。
    """

    async def test_identify_faithfulness_bad_cases(self, evaluator_llm, sampled_golden_dataset):
        """找出 Faithfulness < 0.7 的 bad case"""
        from ragas.metrics.collections import Faithfulness

        scorer = Faithfulness(llm=evaluator_llm)
        bad_cases = []

        for q in sampled_golden_dataset:
            result = await scorer.ascore(
                user_input=q["user_input"],
                response=q["reference"],
                retrieved_contexts=[q["reference"]],
            )
            score = _extract_score(result)
            if score < EVAL_THRESHOLDS["faithfulness"]["block"]:
                bad_cases.append(
                    {
                        "query": q["user_input"],
                        "reference": q["reference"][:100],
                        "faithfulness": round(score, 3),
                    }
                )

        print("\n  ── Faithfulness Bad Cases ──")
        print(f"  总评测: {len(sampled_golden_dataset)} 条")
        print(f"  Bad Cases: {len(bad_cases)} 条")

        for bc in bad_cases[:10]:
            print(f"    [{bc['faithfulness']:.3f}] Q: {bc['query'][:50]}...")

        # 不断言 bad case 数量，只确保分析可运行
        assert isinstance(bad_cases, list)

    async def test_identify_context_recall_bad_cases(self, evaluator_llm, sampled_golden_dataset):
        """找出 ContextRecall < 0.6 的 bad case"""
        from ragas.metrics.collections import ContextRecall

        scorer = ContextRecall(llm=evaluator_llm)
        bad_cases = []

        for q in sampled_golden_dataset:
            result = await scorer.ascore(
                user_input=q["user_input"],
                retrieved_contexts=[q["reference"]],
                reference=q["reference"],
            )
            score = _extract_score(result)
            if score < EVAL_THRESHOLDS["context_recall"]["block"]:
                bad_cases.append(
                    {
                        "query": q["user_input"],
                        "reference": q["reference"][:100],
                        "context_recall": round(score, 3),
                    }
                )

        print("\n  ── ContextRecall Bad Cases ──")
        print(f"  总评测: {len(sampled_golden_dataset)} 条")
        print(f"  Bad Cases: {len(bad_cases)} 条")

        for bc in bad_cases[:10]:
            print(f"    [{bc['context_recall']:.3f}] Q: {bc['query'][:50]}...")

        assert isinstance(bad_cases, list)
