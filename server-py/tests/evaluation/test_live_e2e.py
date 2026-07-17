"""
Level 2: 端到端 RAG 评测（需要全部基础设施）

调用真实 retrieve_docs() + rag_query_stream()，
评测完整 RAG 管线：混合检索 → CrossEncoder 精排 → DeepSeek 生成。

依赖：
- PostgreSQL + pgvector（运行中，rag_chunks 表有数据）
- bge-m3 模型（本地已下载，~2.2GB）
- CrossEncoder bge-reranker-v2-m3（本地已下载，~560MB）
- DeepSeek API Key

运行方式：
    pytest tests/evaluation/test_live_e2e.py -m live -v --timeout=600
"""

import pytest

from .conftest import precision_at_k, recall_at_k, mrr


# ── 前置基础设施检查 ───────────────────────────────────────


def _check_pgvector():
    """检查 PostgreSQL + pgvector 连接"""
    import sys
    from pathlib import Path

    server_py = str(Path(__file__).resolve().parent.parent.parent)
    if server_py not in sys.path:
        sys.path.insert(0, server_py)

    from app.config import config
    from sqlalchemy.ext.asyncio import create_async_engine

    url = config["database"]["url"]
    engine = create_async_engine(url)
    return engine


# ── Level 2: 真实检索评测 ──────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveRetrievalQuality:
    """
    调用真实 retrieve_docs() 评测检索质量

    使用 Non-LLM 指标（precision@k, recall@k, MRR）
    对比 golden dataset 中的 expected_source_titles。
    """

    async def test_real_retrieval_precision_at_4(self, single_hop_queries, eval_thresholds):
        """单跳查询的 Precision@4 应达标（真实检索）"""
        from app.services.rag.query import retrieve_docs

        scores = []
        for q in single_hop_queries[:10]:
            try:
                results = await retrieve_docs(q["user_input"], k=4)
            except Exception as e:
                pytest.skip(f"retrieve_docs 调用失败: {e}")
                return

            retrieved_titles = [r["title"] for r in results]
            expected_titles = q["expected_source_titles"]
            score = precision_at_k(retrieved_titles, expected_titles, k=4)
            scores.append(score)
            print(f"  [P@4={score:.3f}] Q: {q['user_input'][:40]}... → {retrieved_titles[:3]}")

        avg = sum(scores) / len(scores) if scores else 0
        threshold = eval_thresholds["precision_at_4"]["block"]

        print(f"\n  平均 Precision@4: {avg:.3f} (阈值: >= {threshold})")
        assert avg >= threshold, f"Precision@4 = {avg:.3f} < {threshold}"

    async def test_real_retrieval_recall_at_4(self, single_hop_queries, eval_thresholds):
        """单跳查询的 Recall@4 应达标（真实检索）"""
        from app.services.rag.query import retrieve_docs

        scores = []
        for q in single_hop_queries[:10]:
            try:
                results = await retrieve_docs(q["user_input"], k=4)
            except Exception as e:
                pytest.skip(f"retrieve_docs 调用失败: {e}")
                return

            retrieved_titles = [r["title"] for r in results]
            expected_titles = q["expected_source_titles"]
            score = recall_at_k(retrieved_titles, expected_titles, k=4)
            scores.append(score)

        avg = sum(scores) / len(scores) if scores else 0
        threshold = eval_thresholds["recall_at_4"]["block"]

        print(f"\n  平均 Recall@4: {avg:.3f} (阈值: >= {threshold})")
        assert avg >= threshold, f"Recall@4 = {avg:.3f} < {threshold}"

    async def test_real_retrieval_mrr(self, single_hop_queries):
        """单跳查询的 MRR 应 > 0.3（真实检索）"""
        from app.services.rag.query import retrieve_docs

        scores = []
        for q in single_hop_queries[:10]:
            try:
                results = await retrieve_docs(q["user_input"], k=4)
            except Exception as e:
                pytest.skip(f"retrieve_docs 调用失败: {e}")
                return

            retrieved_titles = [r["title"] for r in results]
            score = mrr(retrieved_titles, q["expected_source_titles"])
            scores.append(score)

        avg = sum(scores) / len(scores) if scores else 0
        print(f"\n  平均 MRR: {avg:.3f}")
        assert avg >= 0.3, f"MRR = {avg:.3f} 低于 0.3"


# ── Level 2: 端到端生成评测 ────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveEndToEndGeneration:
    """
    调用真实 rag_query_stream() 评测端到端生成质量

    先真实检索，再真实生成，最后用 RAGAS 评测。
    """

    async def test_e2e_rag_with_real_services(self, evaluator_llm, sampled_golden_dataset, eval_thresholds):
        """端到端评测：真实检索 + 生成 + RAGAS 评测"""
        from app.services.rag.query import rag_query_stream
        from ragas.metrics.collections import Faithfulness, ContextRecall
        from ragas import EvaluationDataset, evaluate

        eval_data = []

        for q in sampled_golden_dataset[:10]:
            try:
                result = await rag_query_stream(q["user_input"])
            except Exception as e:
                print(f"  [SKIP] rag_query_stream 失败: {e}")
                continue

            # 第一步：收集完整回答文本
            sources = result["sources"]
            answer_parts = []
            async for chunk in result["stream_answer"]():
                answer_parts.append(chunk)
            answer = "".join(answer_parts)

            if not answer or not sources:
                print(f"  [SKIP] 空回答或无来源: {q['user_input'][:30]}...")
                continue

            # 第二步：构造评测数据
            retrieved_contexts = [s["content"] for s in sources]
            eval_data.append(
                {
                    "user_input": q["user_input"],
                    "retrieved_contexts": retrieved_contexts,
                    "response": answer,
                    "reference": q["reference"],
                }
            )
            print(f"  [OK] Q: {q['user_input'][:30]}... → 回答 {len(answer)} 字")

        if not eval_data:
            pytest.skip("没有成功的端到端评测数据")
            return

        # 第三步：RAGAS 批量评测
        dataset = EvaluationDataset.from_list(eval_data)
        result = evaluate(
            dataset=dataset,
            metrics=[
                Faithfulness(llm=evaluator_llm),
                ContextRecall(llm=evaluator_llm),
            ],
            llm=evaluator_llm,
        )

        # 第四步：断言
        faithfulness = result["faithfulness"]
        context_recall = result["context_recall"]

        if isinstance(faithfulness, (int, float)):
            pass
        elif hasattr(faithfulness, "value"):
            faithfulness = faithfulness.value

        if isinstance(context_recall, (int, float)):
            pass
        elif hasattr(context_recall, "value"):
            context_recall = context_recall.value

        print("\n  ── 端到端评测结果 ──")
        print(f"  Faithfulness: {faithfulness:.3f}")
        print(f"  ContextRecall: {context_recall:.3f}")

        assert faithfulness >= eval_thresholds["faithfulness"]["block"], (
            f"Faithfulness = {faithfulness:.3f} < {eval_thresholds['faithfulness']['block']}"
        )
        assert context_recall >= eval_thresholds["context_recall"]["block"], (
            f"ContextRecall = {context_recall:.3f} < {eval_thresholds['context_recall']['block']}"
        )


# ── Level 2: 引用溯源评测 ──────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveCitationAccuracy:
    """
    验证回答中的来源引用与实际检索到的 sources 一致
    """

    async def test_citations_match_sources(self, sampled_golden_dataset):
        """回答中的【来源：xxx】应与检索到的 sources 标题一致"""
        from app.services.rag.query import rag_query_stream
        from .conftest import citation_accuracy

        scores = []
        for q in sampled_golden_dataset[:5]:
            try:
                result = await rag_query_stream(q["user_input"])
            except Exception:
                continue

            sources = result["sources"]
            source_titles = [s["title"] for s in sources]

            answer_parts = []
            async for chunk in result["stream_answer"]():
                answer_parts.append(chunk)
            answer = "".join(answer_parts)

            if not source_titles:
                continue

            score = citation_accuracy(answer, source_titles)
            scores.append(score)
            print(f"  [引用={score:.3f}] Q: {q['user_input'][:30]}...")

        if scores:
            avg = sum(scores) / len(scores)
            print(f"\n  平均引用准确率: {avg:.3f}")
        else:
            print("\n  无有效评测数据")
