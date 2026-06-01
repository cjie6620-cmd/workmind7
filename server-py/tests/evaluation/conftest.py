"""
评测专用 fixtures 和自定义指标函数

提供 Non-LLM 检索评测指标（precision@k, recall@k, MRR 等），
评测阈值配置，以及 Live 模式的 RAGAS 评测器 fixtures。
"""

import os
import random
from typing import List

import pytest

# ── CI 门禁阈值（遵循 rag-evaluation.md 规范）─────────────────

EVAL_THRESHOLDS = {
    'faithfulness': {'block': 0.70, 'warn': 0.85},
    'context_recall': {'block': 0.60, 'warn': 0.80},
    'factual_correctness': {'block': 0.60, 'warn': 0.75},
    # Precision@4: 大多数单跳查询只有 1 个期望文档，top4 中命中 1 个 = 0.25
    # 阈值设为 0.20，即至少命中 1 个期望文档（≥1/4）
    'precision_at_4': {'block': 0.20, 'warn': 0.50},
    'recall_at_4': {'block': 0.60, 'warn': 0.75},
}


# ── Non-LLM 自定义指标 ────────────────────────────────────────

def precision_at_k(retrieved_titles: List[str], expected_titles: List[str], k: int) -> float:
    """
    Precision@K：前 k 个检索结果中，有多少比例是相关的

    参数：
    - retrieved_titles: 检索返回的文档标题列表（按相关性排序）
    - expected_titles: 期望的相关文档标题列表
    - k: 截断位置

    返回：0~1 的精确度
    """
    if not retrieved_titles or not expected_titles:
        return 0.0

    top_k = retrieved_titles[:k]
    relevant = sum(1 for t in top_k if _title_match(t, expected_titles))
    return relevant / min(k, len(top_k)) if top_k else 0.0


def recall_at_k(retrieved_titles: List[str], expected_titles: List[str], k: int) -> float:
    """
    Recall@K：期望的相关文档中，有多少比例出现在前 k 个检索结果中

    参数同 precision_at_k

    返回：0~1 的召回率
    """
    if not retrieved_titles or not expected_titles:
        return 0.0

    top_k = retrieved_titles[:k]
    found = sum(1 for t in expected_titles if _title_match(t, top_k))
    return found / len(expected_titles)


def mrr(retrieved_titles: List[str], expected_titles: List[str]) -> float:
    """
    MRR（Mean Reciprocal Rank）：第一个相关结果的倒数排名

    参数同 precision_at_k

    返回：0~1 的 MRR 值
    """
    if not retrieved_titles or not expected_titles:
        return 0.0

    for i, title in enumerate(retrieved_titles):
        if _title_match(title, expected_titles):
            return 1.0 / (i + 1)
    return 0.0


def citation_accuracy(answer: str, expected_sources: List[str]) -> float:
    """
    引用准确率：回答中引用了多大比例的期望来源

    参数：
    - answer: 生成的回答文本
    - expected_sources: 期望的来源文档标题列表

    返回：0~1 的引用准确率
    """
    if not expected_sources:
        return 1.0

    found = sum(1 for src in expected_sources if src in answer)
    return found / len(expected_sources)


def _title_match(title: str, candidates: List[str]) -> bool:
    """模糊匹配标题（去除扩展名后比较）"""
    clean = title.replace('.txt', '').replace('.md', '').strip()
    for c in candidates:
        c_clean = c.replace('.txt', '').replace('.md', '').strip()
        if clean == c_clean or clean in c or c_clean in title:
            return True
    return False


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def eval_thresholds():
    """返回评测阈值配置"""
    return EVAL_THRESHOLDS


@pytest.fixture
def single_hop_queries(golden_dataset):
    """筛选单跳查询"""
    return [q for q in golden_dataset if q['query_type'].startswith('single_hop')]


@pytest.fixture
def multi_hop_queries(golden_dataset):
    """筛选多跳查询"""
    return [q for q in golden_dataset if q['query_type'].startswith('multi_hop')]


@pytest.fixture
def edge_case_queries(golden_dataset):
    """筛选边缘用例"""
    return [q for q in golden_dataset if q['query_type'] == 'edge_case']


# ── Live 评测 Fixtures（@pytest.mark.live 测试使用）───────────

@pytest.fixture(scope="session")
def check_deepseek_api_key():
    """前置检查：DEEPSEEK_API_KEY 必须是真实 key（非测试占位符）"""
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key or key.startswith('test-') or key.startswith('eval-'):
        pytest.skip('DEEPSEEK_API_KEY 未配置或为测试占位符，跳过 live 评测')


@pytest.fixture(scope="session")
def evaluator_llm(check_deepseek_api_key):
    """
    创建 RAGAS 评测用 LLM（DeepSeek API）

    使用 llm_factory + AsyncOpenAI 客户端包装，
    遵循 rag-evaluation.md §5.2 国产模型适配规范。
    """
    from ragas.llms import llm_factory
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ['DEEPSEEK_API_KEY'],
        base_url="https://api.deepseek.com",
    )
    return llm_factory("deepseek-chat", provider="openai", client=client)


@pytest.fixture(scope="session")
def ragas_metrics(evaluator_llm):
    """
    创建 RAGAS 评测指标实例列表

    包含三个核心指标（遵循 rag-evaluation.md §四 推荐最小指标集）：
    - Faithfulness：回答是否基于上下文（不需要 reference）
    - ContextRecall：相关文档是否被检索到（需要 reference）
    - FactualCorrectness：回答与标准答案的事实一致性（需要 reference）
    """
    from ragas.metrics.collections import Faithfulness, ContextRecall, FactualCorrectness
    return [
        Faithfulness(llm=evaluator_llm),
        ContextRecall(llm=evaluator_llm),
        FactualCorrectness(llm=evaluator_llm, mode="f1"),
    ]


@pytest.fixture
def eval_sample_size():
    """评测样本数，可通过 EVAL_SAMPLE_SIZE 环境变量覆盖"""
    return int(os.environ.get('EVAL_SAMPLE_SIZE', '20'))


@pytest.fixture
def sampled_golden_dataset(golden_dataset, eval_sample_size):
    """
    从 golden dataset 按比例分层采样

    保证每种 query_type 都有覆盖，总数由 eval_sample_size 控制。
    使用固定随机种子确保可复现。
    """
    random.seed(42)
    by_type = {}
    for q in golden_dataset:
        qt = q['query_type']
        by_type.setdefault(qt, []).append(q)

    total = eval_sample_size
    per_type = max(2, total // max(len(by_type), 1))
    sampled = []
    for qt, items in by_type.items():
        n = min(per_type, len(items))
        sampled.extend(random.sample(items, n))

    return sampled[:total]
