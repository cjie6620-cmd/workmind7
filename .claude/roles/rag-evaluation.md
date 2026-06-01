> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：RAGAS 0.4.3+（Collections API）/ LangChain 1.0+
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者
>
> **[严重] Legacy API 禁令**：`SingleTurnSample` + `single_turn_ascore` 已废弃，1.0 版本将移除。
> 新项目使用 Legacy API 视为 **[严重] 阻断合并**。

# RAG 评测规范

> 适用场景：RAG 评测、指标设计、评测流水线、CI 门禁。
>
> 本文件是 Python + FastAPI + Agent + RAG 项目的 **RAG 评测核心规范**，与 [agent.md](agent.md) 形成「网状约束」。
>
> 主要工具：RAGAS v0.4.3（docs.ragas.io）

---

## 一、本质结论

**一句话结论**：RAG 评测 = 用数据驱动的方式量化 RAG 系统质量，避免"改了 Prompt 就上线"的赌博行为。

**核心类比**：
- 不评测 = 考试不看分数
- 评测无门禁 = 看了分数但不决定升学
- 评测 + 门禁 = 分数决定升学

**关键点**：
1. RAGAS 是 RAG 评测的主流工具，指标更专业
2. 最小指标集：Faithfulness + ContextRecall + FactualCorrectness
3. 评测 LLM 必须用国产模型（deepseek-chat），禁止国外 API
4. CI 门禁必须配置，回归阈值必须设定

---

## 二、RAGAS 核心概念

### 2.1 基础信息

| 项 | 值 |
|---|---|
| **最新版本** | ragas 0.4.3 (2026-01-13) |
| **Python 要求** | >= 3.9 |
| **协议** | Apache-2.0 |
| **安装** | `pip install ragas` 或 `uv add ragas` |

**API 迁移提示**：0.4 版本将废弃 Legacy API（`SingleTurnSample` + `single_turn_ascore`），1.0 版本移除。**新项目必须使用 Collections API**。

---

### 2.2 指标分类（按机制）

| 类型 | 说明 | 特点 |
|------|------|------|
| **LLM-based** | 用 LLM 做评判 | 更接近人类评估，有一定不确定性 |
| **Non-LLM-based** | 字符串相似度、BLEU 等 | 确定性强，与人类评估相关性较低 |

---

### 2.3 指标分类（按输出类型）

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| **DiscreteMetric** | 返回离散类别（pass/fail, good/ok/bad） | 分类评估、安全检查 |
| **NumericMetric** | 返回数值（0~1 范围） | 连续评分、统计分析 |
| **RankingMetric** | 返回排序列表 | 多输出对比 |

---

### 2.4 指标分类（按评估层次）

| 层次 | 说明 | 示例 |
|------|------|------|
| **End-to-End** | 黑盒评估，用户视角 | 答案正确性、引用准确性 |
| **Component-Level** | 组件独立评估 | 检索精度、生成质量 |
| **Business** | 业务指标，滞后指标 | 工单减少率 |

---

### 2.5 指标设计五原则

1. **Single-Aspect Focus** — 一个指标只衡量一个维度
2. **Intuitive and Interpretable** — 易于理解和解释
3. **Effective Prompt Flows** — 分解复杂任务为子任务
4. **Robustness** — 充足的 few-shot 示例
5. **Consistent Scoring Ranges** — 归一化到 0~1

---

## 三、RAG 核心评估指标（必须掌握）

### 3.1 Faithfulness（忠实度）

**本质**：回答是否完全基于检索到的上下文，不编造信息。

**公式**：
```
Faithfulness = 被上下文支持的声明数 / 回答中总声明数
```

**计算流程**：
1. 将回答拆解为独立声明（claims）
2. 逐一验证每个声明能否从检索上下文中推断
3. 计算比例

**分数范围**：0~1，越高越好

**示例**：
- 上下文: "爱因斯坦 1879 年 3 月 14 日出生于德国"
- 高忠实度回答: "爱因斯坦 1879 年 3 月 14 日出生于德国" → 1.0
- 低忠实度回答: "爱因斯坦 1879 年 3 月 20 日出生于德国" → 0.5（1/2 声明正确）

**代码**：
```python
from ragas.metrics.collections import Faithfulness
from ragas.llms import llm_factory

llm = llm_factory("deepseek-chat")  # 按项目规范用国产模型
scorer = Faithfulness(llm=llm)

result = await scorer.ascore(
    user_input="爱因斯坦何时出生？",
    response="爱因斯坦 1879 年出生于德国",
    retrieved_contexts=["爱因斯坦（1879 年 3 月 14 日出生）是德国理论物理学家"]
)
print(result.value)  # 1.0
```

**特殊变体**：`FaithfulnesswithHHEM` — 使用 Vectara 的 HHEM-2.1-Open（T5 分类器）替代 LLM 做声明验证，适合生产环境降低成本。

---

### 3.2 Context Precision（上下文精确度）

**本质**：检索器把相关文档排在前面的能力。评估的是排序质量，不只是召回。

**公式**：
```
Context Precision@K = Σ(Precision@k × v_k) / K 处相关文档总数

其中 Precision@k = 前 k 个中相关文档数 / k
      v_k ∈ {0, 1} 是第 k 位的相关性指示器
```

**分数范围**：0~1，越高越好

**关键点**：相关文档排第一 vs 排第二，分数差异巨大（0.99 vs 0.5）。

**代码**：
```python
from ragas.metrics.collections import ContextPrecision

scorer = ContextPrecision(llm=llm)
result = await scorer.ascore(
    user_input="埃菲尔铁塔在哪？",
    reference="埃菲尔铁塔在巴黎",
    retrieved_contexts=[
        "埃菲尔铁塔位于巴黎",       # 相关，排第一 → 高精确度
        "勃兰登堡门位于柏林"         # 不相关
    ]
)
# result.value ≈ 1.0
```

---

### 3.3 Context Recall（上下文召回率）

**本质**：有多少相关文档/信息被成功检索到。关注"不遗漏"。

**公式**：
```
Context Recall = 被上下文支持的 reference 声明数 / reference 中总声明数
```

**计算流程**：
1. 将 reference 答案拆解为声明
2. 逐一检查每个声明能否从检索上下文中归因
3. 计算比例

**分数范围**：0~1，越高越好

**关键点**：必须有 reference 才能计算。用 reference 替代 reference_contexts，降低了标注成本。

**代码**：
```python
from ragas.metrics.collections import ContextRecall

scorer = ContextRecall(llm=llm)
result = await scorer.ascore(
    user_input="埃菲尔铁塔在哪？",
    retrieved_contexts=["巴黎是法国首都"],
    reference="埃菲尔铁塔位于巴黎"
)
# result.value = 1.0
```

---

### 3.4 Factual Correctness（事实正确性）

**本质**：回答与标准答案的事实一致性，使用 Precision/Recall/F1 评估。

**公式**：
```
Precision = TP / (TP + FP)   -- 回答中有多少声明被 reference 支持
Recall    = TP / (TP + FN)   -- reference 中有多少声明出现在回答中
F1        = 2 × P × R / (P + R)
```

**独特参数**：

| 参数 | 值 | 说明 |
|------|-----|------|
| `mode` | `f1` / `precision` / `recall` | 默认 f1 |
| `atomicity` | `high` / `low` | 声明拆解粒度 |
| `coverage` | `high` / `low` | 覆盖全面程度 |

**代码**：
```python
from ragas.metrics.collections import FactualCorrectness

scorer = FactualCorrectness(llm=llm, mode="f1")
result = await scorer.ascore(
    response="埃菲尔铁塔在巴黎",
    reference="埃菲尔铁塔在巴黎，高 1000 英尺"
)
# result.value = 0.67（只有 1/2 个 reference 声明被覆盖）
```

---

### 3.5 其他重要指标

#### Noise Sensitivity（噪声敏感度）

**本质**：系统因使用了检索到的文档（相关或不相关）而产生错误回答的频率。**越低越好**。

**公式**：
```
Noise Sensitivity = 回答中错误声明数 / 回答中总声明数
```

**两种模式**：
- `mode="relevant"` — 衡量在相关文档中产生错误的比例
- `mode="irrelevant"` — 衡量被不相关文档误导的比例

---

#### Context Entities Recall（上下文实体召回率）

**本质**：检索上下文覆盖了 reference 中多少实体。适合事实密集型场景（历史问答、旅游客服等）。

**公式**：
```
Context Entity Recall = |RCE ∩ RE| / |RE|
RCE = 检索上下文中的实体集
RE  = reference 中的实体集
```

---

#### Semantic Similarity（语义相似度）

**本质**：回答与标准答案的语义相似程度，基于 embedding 余弦相似度。

**计算**：向量化 → 余弦相似度 → 0~1 分数。**Non-LLM 指标**，不需要 LLM 调用。

---

#### Aspect Critique（方面评估）

**本质**：二元评估，检查回答是否符合特定方面（安全性、正确性、连贯性、简洁性等）。

**内置方面**：harmfulness, maliciousness, coherence, correctness, conciseness

**代码**：
```python
from ragas.metrics import DiscreteMetric

safety_metric = DiscreteMetric(
    name="harmfulness",
    allowed_values=["safe", "unsafe"],
    prompt="评估回答是否可能造成伤害。\n回答: {response}\n仅回答 'safe' 或 'unsafe'",
    llm=llm
)
```

---

## 四、完整 RAG 指标速查表

| 指标 | 评估对象 | 需要 reference | LLM-based | 分数方向 |
|------|---------|---------------|-----------|---------|
| **Faithfulness** | 生成质量 | 否 | 是 | 越高越好 |
| **ContextPrecision** | 检索排序 | 是 | 是 | 越高越好 |
| **ContextUtilization** | 检索排序 | 否（用 response） | 是 | 越高越好 |
| **ContextRecall** | 检索覆盖 | 是 | 是 | 越高越好 |
| **ContextEntityRecall** | 检索覆盖 | 是 | 是 | 越高越好 |
| **FactualCorrectness** | 端到端 | 是 | 是 | 越高越好 |
| **NoiseSensitivity** | 鲁棒性 | 是 | 是 | 越低越好 |
| **SemanticSimilarity** | 端到端 | 是 | 否 | 越高越好 |
| **DiscreteMetric** | 自定义 | 自定义 | 是 | 按定义 |

**推荐最小指标集（RAG 评测必须覆盖）**：
```
Faithfulness + ContextRecall + FactualCorrectness
```

---

## 五、RAGAS 使用方式（Python + FastAPI 落地）

### 5.1 新版 Collections API（推荐）

```python
import asyncio
from ragas.metrics.collections import Faithfulness, ContextRecall, FactualCorrectness
from ragas.llms import llm_factory
from ragas import EvaluationDataset

# 第一步：初始化评估 LLM（项目规范要求用国产模型）
llm = llm_factory("deepseek-chat")  # 通过 OpenAI 兼容接口

# 第二步：准备评估数据集
dataset = EvaluationDataset.from_list([
    {
        "user_input": "什么是 RAG？",
        "retrieved_contexts": ["RAG 是检索增强生成..."],
        "response": "RAG 是检索增强生成技术",
        "reference": "RAG（检索增强生成）是一种结合检索和生成的 AI 技术",
    }
])

# 第三步：执行评估
from ragas import evaluate
result = evaluate(
    dataset=dataset,
    metrics=[
        Faithfulness(llm=llm),
        ContextRecall(llm=llm),
        FactualCorrectness(llm=llm),
    ],
    llm=llm,
)

# 第四步：查看结果
print(result)  # {'faithfulness': 0.9, 'context_recall': 1.0, 'factual_correctness': 0.92}
```

---

### 5.2 自定义评估 LLM（国产模型适配）

```python
from openai import AsyncOpenAI
from ragas.llms import llm_factory

# DeepSeek 兼容 OpenAI 接口
client = AsyncOpenAI(
    api_key="your-deepseek-key",
    base_url="https://api.deepseek.com"
)
llm = llm_factory("deepseek-chat", provider="openai", client=client)

# 通义千问
client = AsyncOpenAI(
    api_key="your-qwen-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
llm = llm_factory("qwen-plus", provider="openai", client=client)
```

---

### 5.3 与 LangChain 集成

```python
from langchain_openai import ChatOpenAI
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import LLMContextRecall, Faithfulness, FactualCorrectness

langchain_llm = ChatOpenAI(model="deepseek-chat", base_url="https://api.deepseek.com")
evaluator_llm = LangchainLLMWrapper(langchain_llm)

result = evaluate(
    dataset=evaluation_dataset,
    metrics=[LLMContextRecall(), Faithfulness(), FactualCorrectness()],
    llm=evaluator_llm,
)
```

---

### 5.4 自定义指标（装饰器方式）

```python
from ragas.metrics import discrete_metric, numeric_metric

# 离散指标
@discrete_metric(name="domain_relevance", allowed_values=["relevant", "irrelevant"])
def domain_relevance(predicted: str, expected: str) -> str:
    return "relevant" if any(kw in predicted.lower() for kw in ["rag", "llm"]) else "irrelevant"

# 数值指标
@numeric_metric(name="response_accuracy", allowed_values=(0, 1))
def response_accuracy(predicted: float, expected: float) -> float:
    return abs(predicted - expected) / max(expected, 1e-5)
```

---

### 5.5 同步 vs 异步

```python
# 异步（推荐）
result = await scorer.ascore(user_input="...", response="...", retrieved_contexts=[...])

# 同步
result = scorer.score(user_input="...", response="...", retrieved_contexts=[...])
```

---

## 六、评测数据集设计规范

### 6.1 理想数据集四特征

1. **高质量样本** — 人工审核 golden dataset
2. **覆盖多种场景** — 单跳/多跳、具体/抽象查询
3. **统计显著数量** — 至少 50~100 条
4. **持续更新** — 防止数据漂移

---

### 6.2 查询类型覆盖

| 查询类型 | 说明 | 示例 |
|----------|------|------|
| **Single-Hop Specific** | 单文档事实查询 | "爱因斯坦哪年发表相对论？" |
| **Single-Hop Abstract** | 单文档抽象理解 | "相对论如何改变了时空观？" |
| **Multi-Hop Specific** | 多文档交叉事实 | "谁影响了爱因斯坦的相对论研究？" |
| **Multi-Hop Abstract** | 多文档综合分析 | "相对论自发表以来如何演变？" |

---

### 6.3 RAGAS 测试集生成（Knowledge Graph 方式）

```python
from ragas.testset.graph import KnowledgeGraph, Node
from ragas.testset.transforms import apply_transforms, Parallel
from ragas.testset.transforms.extractors import NERExtractor, KeyphraseExtractor
from ragas.testset.transforms.relationship_builders.traditional import JaccardSimilarityBuilder

# 第一步：构建知识图谱
kg = KnowledgeGraph.from_documents(documents)

# 第二步：提取实体和关键词，建立关系
transforms = [
    Parallel(NERExtractor(), KeyphraseExtractor()),
    JaccardSimilarityBuilder(property_name="entities")
]
apply_transforms(kg, transforms)

# 第三步：生成测试集
# 基于图谱遍历，自动生成单跳/多跳查询
```

---

### 6.4 数据集格式

```python
from ragas import EvaluationDataset

dataset = EvaluationDataset.from_list([
    {
        "user_input": "用户问题",
        "retrieved_contexts": ["检索到的文档片段1", "片段2"],
        "response": "模型生成的回答",
        "reference": "标准答案（可选，部分指标需要）",
    }
])
```

---

## 七、CI/CD 集成与回归门禁

### 7.1 pytest 集成模式

```python
# tests/test_rag_evaluation.py
import pytest
import asyncio
from ragas import evaluate
from ragas.metrics.collections import Faithfulness, FactualCorrectness
from ragas.llms import llm_factory

# 门禁阈值
THRESHOLDS = {
    "faithfulness": 0.8,
    "factual_correctness": 0.7,
}

@pytest.fixture
def evaluator_llm():
    return llm_factory("deepseek-chat")

@pytest.fixture
def golden_dataset():
    """从 CSV/JSON 加载 golden dataset"""
    return EvaluationDataset.from_list(load_golden_data())

def test_rag_faithfulness(evaluator_llm, golden_dataset):
    result = evaluate(
        dataset=golden_dataset,
        metrics=[Faithfulness(llm=evaluator_llm)],
        llm=evaluator_llm,
    )
    assert result["faithfulness"] >= THRESHOLDS["faithfulness"], \
        f"Faithfulness {result['faithfulness']:.3f} 低于阈值 {THRESHOLDS['faithfulness']}"

def test_rag_factual_correctness(evaluator_llm, golden_dataset):
    result = evaluate(
        dataset=golden_dataset,
        metrics=[FactualCorrectness(llm=evaluator_llm)],
        llm=evaluator_llm,
    )
    assert result["factual_correctness"] >= THRESHOLDS["factual_correctness"]
```

---

### 7.2 CI Pipeline 配置示例

```yaml
# .github/workflows/rag-eval.yml
name: RAG Evaluation
on:
  pull_request:
    paths: ['app/services/rag/**', 'prompts/**']

jobs:
  rag-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/test_rag_evaluation.py -v
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
```

---

### 7.3 回归门禁策略

| 指标 | 最低阈值 | 建议值 | 说明 |
|------|---------|--------|------|
| Faithfulness | 0.7 | 0.85 | 低于此值禁止合并 |
| Context Recall | 0.6 | 0.8 | 检索覆盖不能退化 |
| Factual Correctness (F1) | 0.6 | 0.75 | 端到端质量底线 |
| Noise Sensitivity | < 0.3 | < 0.15 | 越低越好，高于阈值告警 |

**策略**：
1. 首次建立 baseline → 记录所有指标
2. 设置略低于 baseline 的阈值
3. 每次 PR 必须不低于阈值
4. 定期提升阈值

---

## 八、RAGAS vs DeepEval 对比

| 维度 | RAGAS | DeepEval |
|------|-------|----------|
| **定位** | RAG 评测专精 | 通用 LLM 评测 |
| **核心指标** | Faithfulness, Context Precision/Recall | Hallucination, Answer Relevancy, Bias |
| **测试集生成** | 内置 Knowledge Graph 方式 | 需手动准备 |
| **CI 集成** | pytest 原生支持 | pytest 原生支持 |
| **LangChain 集成** | 深度集成 | 深度集成 |
| **可观测性** | Langfuse 集成 | Langfuse/Arize 集成 |
| **评估 LLM** | 任意 OpenAI 兼容接口 | 任意 LLM |
| **社区活跃度** | 14.2k stars, 活跃 | 活跃 |
| **Non-LLM 指标** | 有（BLEU, ROUGE, 语义相似度） | 有 |
| **优势** | RAG 指标更全面、有合成数据生成 | 更通用、文档更友好 |

**选型建议**：RAG 项目优先用 RAGAS（指标更专业），通用 LLM 评测可搭配 DeepEval。

---

## 九、常见陷阱与最佳实践

### 禁止事项

1. **禁止** 测试中调用真实 LLM API（耗时 + 费用 + 不确定性）
2. **禁止** 评估 LLM 使用国外 API（按项目规范必须用国产模型）
3. **禁止** 不设门禁阈值就跑评测（没有阈值等于没评测）
4. **禁止** 只看平均分不看分布（平均 0.8 可能掩盖 0.2 的 bad case）
5. **禁止** 评测数据集不版本管理（必须纳入 Git）
6. **禁止** 使用 Legacy API（`SingleTurnSample` + `single_turn_ascore`）开始新项目

---

### 强制要求

1. **必须** 用 Collections API（`from ragas.metrics.collections import ...`）
2. **必须** 为评估 LLM 配置重试和超时
3. **必须** mock LLM 返回值做单元测试（mock 模型为 `deepseek-chat`，禁止 mock `gpt-4o`）
4. **必须** 评测数据集随 Prompt/检索配置变更同步更新
5. **必须** 在 CI 中对 RAG 相关代码变更跑评测门禁
6. **必须** 记录每次评测的 baseline 和 diff

---

### 关键建议

1. **先建 baseline**：首次评测记录所有指标作为 baseline，后续对比看 delta
2. **分层评测**：检索和生成分开评测，定位问题更快
3. **关注 bad case**：低分样本逐一分析，比平均分更有价值
4. **定期刷新数据集**：从生产日志中采样真实 query 补充到评测集
5. **控制评测成本**：用 `deepseek-chat` 而非大模型做评估，或混合 LLM + Non-LLM 指标
6. **Prompt 版本化**：评测 Prompt 必须和业务 Prompt 一起版本管理

---

## 十、必须测试的场景清单

- [ ] Faithfulness 指标计算正确性
- [ ] ContextRecall 指标计算正确性
- [ ] FactualCorrectness 指标计算正确性
- [ ] Collections API 使用正确性
- [ ] 国产模型（DeepSeek）适配性
- [ ] 评测数据集加载正确性
- [ ] CI 门禁阈值通过率
- [ ] 回归检测灵敏度（指标退化 > 5% 是否阻断）
- [ ] bad case 分析能力
- [ ] 评测成本可控性

---

## 十一、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **API** | ❌ 测试中调用真实 LLM API；❌ 评估 LLM 使用国外 API（OpenAI / Anthropic） |
| **门禁** | ❌ 不设门禁阈值就跑评测；❌ 只看平均分不看分布；❌ 指标退化不阻断合并 |
| **数据集** | ❌ 评测数据集不版本管理；❌ golden dataset 不人工审核；❌ 数据集不持续更新 |
| **API 版本** | ❌ 使用 Legacy API（SingleTurnSample + single_turn_ascore）开始新项目 |
| **测试** | ❌ 不 mock LLM 返回值做单元测试；❌ mock 模型为 gpt-4o / claude-* |
| **Prompt** | ❌ 评测 Prompt 硬编码；❌ 评测 Prompt 不与业务 Prompt 一起版本管理 |
| **成本** | ❌ 评估 LLM 不配置重试和超时；❌ 不控制评测成本 |

---

## 十二、与其他角色的协作

- **与 [agent.md](agent.md) 的关系**：RAG 评测集成参考 agent.md §十七
- **与 [prompt-engineering.md](prompt-engineering.md) 的关系**：Prompt 优化效果必须通过 RAG 评测验证
- **与 [mcp.md](mcp.md) 的关系**：MCP Tool 的评测参考本规范
- **与 [skill.md](skill.md) 的关系**：Skill 的评测参考本规范

---

**最后更新**：2026-06-01
**维护者**：AI Agent
