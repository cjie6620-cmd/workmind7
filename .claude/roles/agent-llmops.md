> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：LangChain 1.0+ / LangGraph 1.0.8+ / Langfuse 2.x
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Agent 规范 — Memory、可观测与失败回退

> 本文件从 [agent.md](agent.md) 拆出，覆盖 Memory 策略、Langfuse 可观测、Guardrails 和失败回退。
>
> 与 [agent-cost.md](agent-cost.md)（成本监控）/ [devops.md](devops.md)（Langfuse 部署）协同。

---

## 八、Memory 策略

### 8.1 三层 Memory 架构

```
┌────────────────────────────────────────────────────┐
│  L1 短期（In-Context）                              │
│  - 最近 N 轮对话（N=5-10）                            │
│  - 直接拼入 prompt                                  │
│  - 强制 TTL：超过 30 分钟无活动则清空                 │
└────────────────────────────────────────────────────┘
              ↓ 重要信息提炼
┌────────────────────────────────────────────────────┐
│  L2 长期（VectorStore-backed）                      │
│  - 用户偏好 / 实体信息 / 关键事实                     │
│  - 写入：LLM 自动提炼                               │
│  - 检索：每次 query 时做 similarity search           │
└────────────────────────────────────────────────────┘
              ↓ 实体关系
┌────────────────────────────────────────────────────┐
│  L3 实体记忆（Neo4j / Zep）                          │
│  - 用户-实体 关系图谱                                │
│  - 写入：NER 抽取 + 关系抽取                          │
│  - 检索：图查询 + 向量查询                          │
└────────────────────────────────────────────────────┘
```

### 8.2 强制约束

| 规则 | 说明 |
|------|------|
| **TTL 强制** | 短期 memory 单 session 30 分钟无活动自动清空 |
| **Token 限制** | 单次注入 LLM 的 memory 总 token ≤ 4000 |
| **写入去重** | 同一事实 7 天内不重复写入（避免噪声） |
| **删除接口** | 必须提供用户主动删除 memory 的接口（GDPR 合规） |

---

## 九、可观测性（Langfuse 必接）

### 9.1 Trace 链路

**强制**：每一跳 LLM 调用必须打 trace，包含 `prompt` / `response` / `latency` / `token_usage` / `model` / `retrieved_docs`。

```python
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    tags=["production", "rag-pipeline"],
)

llm.invoke(
    messages,
    config={"callbacks": [langfuse_handler]}
)
```

### 9.3 质量监控

| 指标 | 数据源 |
|------|--------|
| **用户反馈** | 👍 / 👎 按钮 → 写入 Langfuse score |
| **引用命中率** | 答案中是否包含 `[n]` 引用 |
| **空检索率** | 检索返回 0 结果的比例 |
| **重生成率** | 同一 session 同 query 重新生成的次数 |

---

## 十一、Guardrails（输入/输出双向）

### 11.1 输入审核

| 风险 | 防护 |
|------|------|
| **Prompt 注入** | 检测 `ignore previous instructions` 等模式，正则 + LLM-as-judge |
| **PII** | 邮箱/手机号/身份证脱敏后再送 LLM |
| **超长输入** | `max_input_tokens=4000`，超出截断 |
| **越权请求** | 业务参数权限校验（在 RAG 检索前） |

### 11.2 输出过滤

| 风险 | 防护 |
|------|------|
| **有害内容** | Guardrails AI toxicity 检测 |
| **幻觉** | 强制要求 answer 中包含至少 1 个 `[n]` 引用 |
| **敏感泄露** | 输出后 LLM-as-judge 检查是否包含训练数据中的 PII |
| **格式错误** | Pydantic schema 校验 |

### 11.3 Token 预算

**三级 Token 配额**：

```python
class TokenBudget:
    PER_REQUEST = 8000      # 单请求 max
    PER_USER_PER_HOUR = 100_000  # 单用户小时
    GLOBAL_PER_MINUTE = 1_000_000  # 全局分钟级（防雪崩）
```

超限处理：返回友好提示 + 排队等待（不直接 500）。

---

## 十三、失败回退

### 13.1 模型降级链

```python
# ✅ 国产模型降级链（全部国内合规）
MODEL_FALLBACK_CHAIN = [
    "deepseek-chat",        # 主模型（主力）
    "deepseek-reasoner",    # 降级 1（推理任务）
    "qwen-plus",            # 降级 2（DeepSeek 不可用）
    "glm-4-plus",           # 降级 3
    "qwen-turbo",           # 降级 4（高 QPS 场景）
    "local-vllm-qwen2.5",   # 降级 5（本地兜底）
]
```

每个降级触发条件：主模型连续 3 次失败 / 延迟 > 10s / 成本超限。

### 13.2 重试 + 熔断

```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def call_llm_with_retry(prompt: str) -> str:
    return retry_call(
        llm.invoke,
        args=[prompt],
        max_attempts=3,
        backoff=ExponentialBackoff(min=1, max=10),
    )
```

### 13.3 检索失败回退

```
向量检索 → 失败 → BM25 → 失败 → 全文搜索（DB LIKE）→ 失败 → 拒答
```

每级降级必须打 trace 标记，方便事后分析。
