> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Agent 规范 — 成本与延迟监控

> 本文件从 [agent.md](agent.md) 拆出，覆盖 Token 预算公式、延迟目标和降级策略。
>
> 与 [agent-llmops.md](agent-llmops.md)（失败回退）/ [devops.md](devops.md)（Prometheus 埋点）协同。

---

## 十、评估（Offline Eval 流水线）

### 10.1 数据集管理

```
eval_dataset/
├── rag_v1/
│   ├── questions.jsonl    # {"q": "...", "expected_answer": "...", "expected_sources": [...]}
│   ├── answers_baseline.jsonl
│   └── README.md          # 标注采集时间、覆盖场景
└── rag_v2/
```

### 10.2 评估指标

| 指标 | 公式 | 工具 |
|------|------|------|
| **faithfulness** | 答案中每个事实是否有 chunk 支持 | RAGAS |
| **answer_relevancy** | 答案与问题相关度 | RAGAS |
| **context_precision** | Top-K 中相关 chunk 占比 | RAGAS |
| **context_recall** | 正确答案所需的 chunk 是否被召回 | RAGAS |
| **answer_correctness** | 答案与标准答案语义相似度 | RAGAS / DeepEval |
| **latency_p95** | P95 响应延迟 | 自研 |
| **cost_p95** | P95 单请求成本 | 自研 |

### 10.3 回归门禁

CI 流水线：
```yaml
- name: Run RAG Eval
  run: |
    uv run pytest tests/eval/ --dataset=eval_dataset/rag_v2 --baseline=baseline.json
    uv run python scripts/eval_report.py --threshold faithfulness=0.85
```

**规则**：
- 新指标必须 ≥ baseline
- 退化 > 5% → 阻断合并
- 退化 > 10% → 自动回滚到上一版本 Prompt

> 详细评测规范见 [rag-evaluation.md](rag-evaluation.md)

---

## 十二、成本与延迟监控

### 12.1 Token 预算公式

```
单次请求总成本 = (input_tokens × input_price) + (output_tokens × output_price)
              = (prompt_tokens + context_tokens + history_tokens + rag_tokens) × input_price
              + (output_tokens) × output_price

其中：
- prompt_tokens      = 系统提示词 token 数（固定，可缓存）
- context_tokens     = RAG 召回 chunk token 数（受 top_k 和 chunk_size 限制）
- history_tokens     = 对话历史 token 数（受 max_messages 限制）
- rag_tokens         = query 改写 + 路由决策的 token 数
- output_tokens      = 生成答案 token 数（受 max_tokens 限制）
```

**优化目标**：在保证 faithfulness > 0.85 的前提下，最小化总成本。

### 12.2 TTFT / TPOT 目标

| 指标 | 目标 | 不可接受 |
|------|------|----------|
| **TTFT** (Time To First Token) | < 1.5s | > 3s |
| **TPOT** (Time Per Output Token) | < 50ms | > 100ms |
| **E2E** (端到端) | < 5s | > 10s |

### 12.3 降级策略

```
优先级从高到低：
1. 语义缓存命中 → 直接返回（< 100ms）
2. 简化模型（qwen-turbo / glm-4-flash / deepseek-chat）→ 牺牲质量换速度
3. 减少 RAG top_k（10 → 3）→ 牺牲召回换速度
4. 截断历史（10 → 3 轮）→ 牺牲上下文换速度
5. 拒绝服务 → 返回 "系统繁忙，请稍后重试"
```

❌ 禁止：所有降级策略都失败时不做任何处理直接 500。

---

## 成本监控（Langfuse）

```python
# ✅ 国产模型成本表（单位：元 / 千 token）
# ⚠️ 成本数据免责：以下价格以各厂商官方计费页面为准，仅供估算参考
# DeepSeek 核实地址：https://platform.deepseek.com/api-docs/pricing
# 通义千问核实地址：https://help.aliyun.com/zh/model-studio/getting-started/models
COST_PER_1K = {
    "deepseek-chat":    {"input": 0.001,  "output": 0.002},
    "deepseek-reasoner": {"input": 0.004,  "output": 0.016},
    "qwen-max":         {"input": 0.040,  "output": 0.120},
    "qwen-plus":        {"input": 0.008,  "output": 0.020},
    "qwen-turbo":       {"input": 0.003,  "output": 0.006},
    "glm-4-plus":       {"input": 0.035,  "output": 0.035},
    "glm-4-flash":      {"input": 0.0001, "output": 0.0001},
    "yi-large":         {"input": 0.020,  "output": 0.020},
    "doubao-pro":       {"input": 0.0008, "output": 0.001},
}
```

Langfuse 看板监控：
- 每请求平均成本
- 每用户日成本 Top 10
- 高成本 query 抽样分析
