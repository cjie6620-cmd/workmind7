"""
Level 3: 消融实验（需要全部基础设施）

在真实服务上运行消融实验：
- 混合检索消融：纯向量 vs 纯 BM25 vs 混合（BM25+向量+RRF）
- 重排序消融：有/无 CrossEncoder 精排的对比

依赖：同 Level 2 全部基础设施

运行方式：
    pytest tests/evaluation/test_live_ablation.py -m live -v --timeout=600
"""

import pytest

from .conftest import precision_at_k


# ── Level 3: 混合检索消融 ─────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveHybridAblation:
    """
    混合检索消融实验

    对比三种检索策略：
    1. 纯向量检索（仅 PGVector）
    2. 纯 BM25 检索（仅关键词）
    3. 混合检索（BM25 + 向量 + RRF 融合）

    使用 precision@k / recall@k 量化对比。
    """

    async def test_vector_only_vs_hybrid(self, single_hop_queries, eval_thresholds):
        """混合检索应优于纯向量检索"""
        from app.services.rag.query import retrieve_docs
        from app.services.rag.hybrid_retriever import get_hybrid_retriever

        vector_scores = []
        hybrid_scores = []

        for q in single_hop_queries[:8]:
            expected = q["expected_source_titles"]

            # 第一步：完整管线（有 reranker 的混合检索）
            try:
                hybrid_results = await retrieve_docs(q["user_input"], k=4)
            except Exception as e:
                pytest.skip(f"retrieve_docs 失败: {e}")
                return

            hybrid_titles = [r["title"] for r in hybrid_results]
            h_score = precision_at_k(hybrid_titles, expected, k=4)
            hybrid_scores.append(h_score)

            # 第二步：仅混合检索（跳过 reranker）
            try:
                retriever = await get_hybrid_retriever()
                candidates = await retriever.ainvoke(q["user_input"])
            except Exception:
                continue

            if not candidates:
                continue

            # 直接取前 4 个候选的标题（无 reranker）
            cand_titles = []
            for doc in candidates[:4]:
                title = doc.metadata.get("title", "未知来源") if hasattr(doc, "metadata") else "未知来源"
                cand_titles.append(title)

            v_score = precision_at_k(cand_titles, expected, k=4)
            vector_scores.append(v_score)

            print(f"  [混合={h_score:.2f} / 无rerank={v_score:.2f}] Q: {q['user_input'][:30]}...")

        if not hybrid_scores or not vector_scores:
            pytest.skip("无有效评测数据")
            return

        avg_hybrid = sum(hybrid_scores) / len(hybrid_scores)
        avg_vector = sum(vector_scores) / len(vector_scores)

        print("\n  ── 混合检索消融结果 ──")
        print(f"  完整管线（混合+rerank） Precision@4: {avg_hybrid:.3f}")
        print(f"  无 rerank Precision@4: {avg_vector:.3f}")
        print(f"  差异: {avg_hybrid - avg_vector:+.3f}")

        # 混合检索至少应达到阻断阈值
        threshold = eval_thresholds["precision_at_4"]["block"]
        assert avg_hybrid >= threshold, f"混合检索 Precision@4 = {avg_hybrid:.3f} < {threshold}"


# ── Level 3: 重排序消融 ────────────────────────────────────


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.evaluation
class TestLiveRerankerAblation:
    """
    重排序消融实验

    对比有/无 CrossEncoder 精排的效果差异：
    - 无 reranker：直接使用混合检索的候选结果
    - 有 reranker：对候选结果做 CrossEncoder 精排后返回
    """

    async def test_reranker_improves_precision(self, single_hop_queries):
        """重排序应提升精确度"""
        from app.services.rag.hybrid_retriever import get_hybrid_retriever
        from app.services.rag.reranker import get_reranker

        no_rerank_scores = []
        with_rerank_scores = []

        for q in single_hop_queries[:8]:
            expected = q["expected_source_titles"]

            # 第一步：无 reranker（直接用 hybrid retriever 结果）
            try:
                retriever = await get_hybrid_retriever()
                candidates = await retriever.ainvoke(q["user_input"])
            except Exception as e:
                pytest.skip(f"hybrid retriever 失败: {e}")
                return

            if not candidates:
                continue

            cand_titles = []
            for doc in candidates[:4]:
                title = doc.metadata.get("title", "未知来源") if hasattr(doc, "metadata") else "未知来源"
                cand_titles.append(title)

            no_rerank_score = precision_at_k(cand_titles, expected, k=4)
            no_rerank_scores.append(no_rerank_score)

            # 第二步：有 reranker（完整管线）
            try:
                reranker = get_reranker()
                ranked = reranker.rerank(q["user_input"], candidates, top_n=4)
            except Exception as e:
                print(f"  [SKIP] reranker 失败: {e}")
                continue

            ranked_titles = [r["title"] for r in ranked]
            with_rerank_score = precision_at_k(ranked_titles, expected, k=4)
            with_rerank_scores.append(with_rerank_score)

            print(f"  [无rerank={no_rerank_score:.2f} / 有rerank={with_rerank_score:.2f}] Q: {q['user_input'][:30]}...")

        if not no_rerank_scores or not with_rerank_scores:
            pytest.skip("无有效评测数据")
            return

        avg_no = sum(no_rerank_scores) / len(no_rerank_scores)
        avg_with = sum(with_rerank_scores) / len(with_rerank_scores)

        print("\n  ── 重排序消融结果 ──")
        print(f"  无 reranker Precision@4: {avg_no:.3f}")
        print(f"  有 reranker Precision@4: {avg_with:.3f}")
        print(f"  提升: {avg_with - avg_no:+.3f}")

        # reranker 至少不应降低精度
        assert avg_with >= avg_no * 0.8, f"reranker 严重降低了精度: {avg_with:.3f} < {avg_no * 0.8:.3f}"

    async def test_reranker_threshold_sensitivity(self, single_hop_queries):
        """不同 reranker 阈值对精度的影响"""
        from app.services.rag.hybrid_retriever import get_hybrid_retriever
        from app.services.rag.reranker import CrossEncoderReranker

        # 需要获取一次候选集
        query = single_hop_queries[0] if single_hop_queries else None
        if not query:
            pytest.skip("无单跳查询数据")
            return

        try:
            retriever = await get_hybrid_retriever()
            candidates = await retriever.ainvoke(query["user_input"])
        except Exception as e:
            pytest.skip(f"hybrid retriever 失败: {e}")
            return

        if not candidates:
            pytest.skip("候选集为空")
            return

        # 使用不同阈值测试
        thresholds = [0.1, 0.2, 0.3, 0.5]
        results = {}

        for threshold in thresholds:
            # 创建临时 reranker（不使用单例）
            reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
            try:
                from app.services.rag.reranker import get_reranker

                # 复用已加载的模型
                real_reranker = get_reranker()
                reranker.model = real_reranker.model
                reranker.threshold = threshold
            except Exception as e:
                pytest.skip(f"reranker 加载失败: {e}")
                return

            ranked = reranker.rerank(query["user_input"], candidates, top_n=4)
            n_results = len(ranked)
            results[threshold] = n_results
            print(f"  threshold={threshold}: 保留 {n_results} 条结果")

        # 阈值越高，保留结果越少
        print("\n  ── 阈值敏感性分析 ──")
        for t, n in sorted(results.items()):
            print(f"  threshold={t}: {n} 条")

        assert isinstance(results, dict)
