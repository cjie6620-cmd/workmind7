> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：LangChain 1.0+ / LangGraph 1.0.8+ / RAGAS 0.4.3+ / MCP SDK 1.12.4+
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Agent 规范（RAG + Agent + LLM Ops）

> 适用场景：Python LLM 应用开发，覆盖 RAG 检索增强、Agent 智能体、LLM 全链路可观测。
>
> 本文件是 Python + FastAPI + Agent + RAG 项目的**核心角色规范**，与 [backend-fastapi.md](backend-fastapi.md) / [dba.md](dba.md) / [devops.md](devops.md) / [frontend.md](frontend.md) / [reviewer.md](reviewer.md) 形成「网状约束」。
>
> **规范分拆说明**：本文件为核心（技术栈 + Agent Loop + Tool + Prompt），子模块拆分为：
> - [agent-rag.md](agent-rag.md) — RAG 检索增强规范（§六）+ VectorStore 规范（§七）
> - [agent-llmops.md](agent-llmops.md) — Memory 策略（§八）+ 可观测性（§九）+ Guardrails（§十一）+ 失败回退（§十三）
> - [agent-cost.md](agent-cost.md) — 评估流水线（§十）+ 成本与延迟监控（§十二）

---

## 一、技术栈选型（必须遵守）

### 1.1 LLM Provider 抽象

> **强制原则**：本项目**禁止使用任何国外 API 模型**（OpenAI / Anthropic / Cohere / Jina 等），**全部使用国产大模型**。主力为 **DeepSeek**，备选为通义千问 / 智谱 GLM / 零一万物等国内合规模型。

| 场景 | 推荐 | 版本 | 备注 |
|------|------|------|------|
| **云端主力** | **DeepSeek (`deepseek-chat` / `deepseek-reasoner`)** | langchain-deepseek 0.1+ | 主力模型、OpenAI 兼容协议、长上下文 64K、Function Calling 稳定、成本极低 |
| **云端备选 A** | 通义千问 (`qwen-max` / `qwen-plus` / `qwen-turbo`) | langchain-qwen 0.1+ | 阿里云百炼平台、合规、稳定、Tool Use 完善 |
| **云端备选 B** | 智谱 GLM (`glm-4-plus` / `glm-4-flash`) | langchain-zhipuai 0.1+ | 清华系、推理能力强、OpenAI 兼容 |
| **云端备选 C** | 零一万物 (`yi-large` / `yi-medium`) | langchain-yi 0.1+ | 长文本（200K）、性价比高 |
| **云端备选 D** | 豆包 (`doubao-pro-128k`) | langchain-volcengine 0.1+ | 字节火山引擎、价格低 |
| **本地生产** | vLLM (Qwen2.5 / DeepSeek-V3 / GLM-4) | vllm 0.6+ | GPU 推理、高吞吐、支持国产开源模型 |
| **本地轻量** | Ollama (Qwen2.5 / DeepSeek-R1-Distill) | ollama 0.4+ | 开发环境、CPU/GPU 通用 |
| **统一抽象** | LangChain `init_chat_model` | langchain 1.0+ | 一行切换 provider，**强制使用** |

**LangChain 1.0 迁移提示**：LangChain 1.0 已于 2025-10 发布。部分旧 `langchain-community` 子包已拆出为独立包（`langchain-text-splitters`、`langchain-mcp-adapters` 等），引入新功能时请核对 import 路径。

❌ **绝对禁止**：在业务代码中调用 OpenAI / Anthropic / Cohere / Jina / OpenRouter 等任何国外 API。

❌ 禁止直接 `import openai` / `import anthropic` 在业务代码中硬编码调用，**必须**通过 LangChain `init_chat_model` 抽象：

```python
# ❌ 反例：直接硬编码国外 provider（禁止）
from openai import OpenAI
client = OpenAI(api_key="sk-...")
resp = client.chat.completions.create(model="gpt-4o", ...)

# ❌ 反例：直接硬编码国产 provider（也不推荐）
from openai import OpenAI
client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
resp = client.chat.completions.create(model="deepseek-chat", ...)

# ✅ 正例：统一抽象（推荐）
from langchain.chat_models import init_chat_model
llm = init_chat_model("deepseek-chat", model_provider="deepseek", temperature=0)
resp = llm.invoke([HumanMessage(content=...)])

# ✅ 正例：备选模型切换（一行完成）
llm_backup = init_chat_model("qwen-plus", model_provider="tongyi", temperature=0)
```

### DeepSeek 集成详细配置

```python
# app/llm/clients.py
from langchain.chat_models import init_chat_model
from app.core.config import settings

# 主力
main_llm = init_chat_model(
    settings.LLM_DEFAULT_MODEL,          # "deepseek-chat"
    model_provider="deepseek",
    api_key=settings.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    temperature=0.2,
    max_tokens=2048,
    timeout=30,
    max_retries=3,
)

# 推理增强（复杂任务用 R1）
reasoner_llm = init_chat_model(
    "deepseek-reasoner",
    model_provider="deepseek",
    api_key=settings.DEEPSEEK_API_KEY,
    temperature=0.6,                      # 推理模型建议 0.5-0.7
    max_tokens=8000,
)

# 备选（DeepSeek 不可用时降级）
backup_llm = init_chat_model(
    "qwen-plus",
    model_provider="tongyi",
    api_key=settings.DASHSCOPE_API_KEY,
    temperature=0.2,
    max_tokens=2048,
)
```

### 1.2 Agent 框架

| 场景 | 推荐 | 理由 |
|------|------|------|
| **生产级复杂 Agent** | **LangGraph 1.0+** | 状态图、可中断、人在回路、可观测性最佳 |
| **轻量单 Agent** | **smolagents** | 代码即 Agent、HuggingFace 生态、几行代码 |
| **多 Agent 协作** | CrewAI / AutoGen | 角色扮演型多 Agent 编排 |
| **LangChain Agent** | ❌ 不推荐 | 已被 LangGraph 取代，LangChain 1.0 已弃用 `AgentExecutor` |

**LangGraph 1.0 迁移提示**：`MemorySaver` 已重命名为 `InMemorySaver`，看到旧写法应立即替换。

```python
# ✅ LangGraph 状态图骨架
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class AgentState(TypedDict):
    messages: list
    context: dict

graph = StateGraph(AgentState)
graph.add_node("think", think_node)
graph.add_node("act", act_node)
graph.add_node("observe", observe_node)
graph.add_edge(START, "think")
graph.add_conditional_edges("think", should_continue, {"act": "act", END: END})
app = graph.compile()
```

### 1.3 RAG 框架

| 场景 | 推荐 | 理由 |
|------|------|------|
| **复杂 RAG（含 Agent、Tool）** | **LangChain 1.0+** | 生态最全、与 LangGraph 无缝集成 |
| **纯检索增强（数据接入为主）** | **LlamaIndex** | 索引抽象更好、DataConnector 多 |
| **简单 QA** | LangChain `RetrievalQA` | 一行代码起步 |

### 1.4 向量库

| 场景 | 推荐 | 理由 |
|------|------|------|
| **生产大规模（>10M 向量）** | **Milvus** | 分布式、HNSW/IVF_PQ 高性能 |
| **生产中等规模 / 一体化** | **PGVector** | 与 PostgreSQL 共部署、事务一致 |
| **轻量 / 边缘部署** | **Qdrant** | Rust 性能、嵌入式模式 |
| **原型 / 本地开发** | **Chroma** | 零运维、文件存储 |
| **企业级 + 混合检索** | **Elasticsearch dense_vector** | 与 ES 现有架构融合 |

> 详细选型决策树见 [agent-rag.md §七](agent-rag.md#七vectorstore-规范)

### 1.5 Embedding 模型管理

> **必须使用国产 Embedding 模型**，与 LLM Provider 约束保持一致，**禁止** OpenAI / Cohere / Jina 等国外 Embedding。

**推荐国产 Embedding 模型**：

| 模型 | 提供商 | 维度 | 适用场景 |
|------|--------|------|---------|
| **BAAI/bge-m3** | 智源（开源，本地部署） | 1024 | 通用中文多语言，**推荐首选** |
| **text-embedding-v3** | 通义千问（阿里云 DashScope） | 1024 / 768 | 云端调用，速度快 |
| **embedding-2** | 智谱 GLM | 1024 | 与 GLM 生态配合 |
| **yi-embedding** | 零一万物 | 2048 | 长文本场景 |
| ❌ text-embedding-3-small | OpenAI | **禁止** | — |

**通用管理规则**：

| 维度 | 必选项 |
|------|--------|
| **模型版本** | 必须固定（如 `BAAI/bge-m3@v1.0`），**禁止**用 `latest` 浮点版本号 |
| **维度** | 必须与向量库索引维度一致（如 1024 / 768），**禁止**混用 |
| **批大小** | 单批 ≤ 2048 chunks，超出需预分桶 |
| **缓存** | 同一文本的 embedding **必须**走 Redis 缓存（key: `emb:{model}:{sha256(text)}`） |
| **升级策略** | 升级 embedding 模型 **必须**触发全量重建索引（写补偿任务），**禁止**静默升级 |

### 1.6 可观测

| 工具 | 用途 | 强制程度 |
|------|------|----------|
| **Langfuse** | Trace 链路 + 成本 + 评估 | **生产必接** |
| **Phoenix (Arize)** | 离线评估 + drift 检测 | 选接 |
| **LangSmith** | LangChain 官方 | 选接（仅 LangChain 生态） |
| **OpenTelemetry** | 统一 trace 协议 | **强制**（所有 LLM 调用必须包 OTel span） |

### 1.7 评估

| 工具 | 用途 |
|------|------|
| **RAGAS** | RAG 指标（faithfulness / answer_relevancy / context_precision） |
| **DeepEval** | 综合 LLM 评估框架 |
| **自研 Eval 流水线** | 业务特定指标 |

### 1.8 Guardrails

| 工具 | 用途 |
|------|------|
| **Guardrails AI** | 输入/输出校验（结构化、PII、毒性） |
| **NeMo Guardrails** | 对话流控制（多轮约束） |
| **自研规则 + LLM-as-judge** | 业务特定规则 |

---

## 二、避坑清单（LLM 专属，20+ 条）

按严重程度排序：

### 🔴 致命（会导致系统不可用 / 数据损坏）

1. **禁止 LLM 调用无 `max_tokens` 上限** → 单次请求可能返回数万 token 耗尽额度；**必须**设置 `max_tokens=2048` 或更小
2. **禁止 LLM 输出 JSON 不经修复直接 parse** → 必须经过 `JsonUtil.fixJson()` 7 步修复管道
3. **禁止 Embedding 模型升级不重建索引** → 新旧向量在同一空间，相似度全乱
4. **禁止父子分段不保留 `parent_chunk_id`** → 检索时无法回溯完整上下文
5. **禁止 ReAct Loop 无 `max_iterations` 兜底** → 死循环耗尽 token（**必须** ≤ 10）
6. **禁止 Tool 调用无 `timeout` / `retry`** → 单个 Tool 卡死阻塞整个 Agent
7. **禁止 VectorStore metadata 无 `tenant_id` / `accessible_by`** → 跨租户数据泄露

### 🟠 严重（会导致生产事故 / 成本失控）

8. **禁止生产用 `temperature > 0.7` 无 eval 验证** → 不可重现、评估指标波动
9. **禁止 Prompt 模板硬编码在业务代码中** → 必须走 Prompt Registry / git-lfs，版本化
10. **禁止 Memory 无 TTL 或显式清理** → 上下文无限膨胀、超 token 限制
11. **禁止 RAG 无引用溯源** → 用户无法验证答案，幻觉无法追溯
12. **禁止并发调用 LLM 无 semaphore 限流** → 触发 provider rate limit
13. **禁止 LLM 调用不捕获异常** → 单次失败导致整个请求 500

### 🟡 重要（会导致质量问题 / 可维护性差）

14. **禁止只做向量检索不做 Re-ranking** → Top-K 召回质量低
15. **禁止只做 dense 不做 sparse（BM25）混合** → 关键词命中差
16. **禁止 Query 不做改写直接检索** → 短查询/口语化查询召回率低
17. **禁止 Chunk 不带 `source` / `score` / `metadata`** → 无法做引用溯源
18. **禁止多轮对话无 conversation_id 串联** → 上下文断裂
19. **禁止在 Prompt 中塞入敏感信息** → 泄露到 provider 日志
20. **禁止 LLM 调用不打 trace** → 线上问题无法排查
21. **禁止不写 offline eval** → Prompt 改了就上线，回归无门禁
22. **禁止不限制 `top_k` 检索数量** → 默认 100+ 召回导致 LLM 输入爆炸

---

## 三、Agent Loop 设计

### 3.1 ReAct 模式（推荐：单 Agent + Tool）

```
┌──────────────────────────────────────────────────────────┐
│                    ReAct Agent Loop                      │
│                                                          │
│   ┌─────────┐    思考     ┌────────────┐                 │
│   │  Query  │───────────▶│   LLM      │                 │
│   └─────────┘            │  (Think)   │                 │
│        ▲                 └─────┬──────┘                 │
│        │                       │                         │
│        │                 ┌─────▼──────┐                 │
│        │                 │  Action?   │                 │
│        │                 └─┬───────┬──┘                 │
│        │                Yes       No                   │
│        │                 │         │                    │
│        │          ┌──────▼──┐  ┌───▼────┐               │
│        │          │  Tool   │  │  Final │               │
│        │          │  Call   │  │ Answer │               │
│        │          └────┬────┘  └───┬────┘               │
│        │               │           │                    │
│        │               └─────┬─────┘                    │
│        │                     │                          │
│        │               ┌─────▼──────┐                  │
│        └───────────────│  Observe   │                  │
│         循环继续        │  Result    │  max_iterations  │
│                        └────────────┘  (默认 5-10)    │
└──────────────────────────────────────────────────────────┘
```

✅ **正确实现（LangGraph 1.0+）**：

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import InMemorySaver  # LangGraph 1.0+ 用 InMemorySaver（旧 MemorySaver 已弃用）

class AgentState(TypedDict):
    messages: list[BaseMessage]
    iteration: int

MAX_ITERATIONS = 10  # 强制兜底

def should_continue(state: AgentState) -> str:
    if state["iteration"] >= MAX_ITERATIONS:
        return END
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END

graph = StateGraph(AgentState)
graph.add_node("agent", call_llm_node)
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

# 强制 checkpoint（人可中断 / 恢复）
app = graph.compile(checkpointer=InMemorySaver())
```

### 3.2 Plan-and-Execute 模式（推荐：复杂多步任务）

```
Plan → Step1 → Observe → Step2 → Observe → ... → Final Answer
  │                                                            ▲
  └────── replan if failed ─────────────────────────────────────┘
```

### 3.3 Reflection 模式（推荐：质量要求高的场景）

```
Generate → Critique (LLM-as-judge) → Revise → ... → Final
                  │                                    ▲
                  └──── not pass ──────────────────────┘
```

### 3.4 多 Agent 协作（CrewAI / AutoGen）

- 角色分工：Researcher / Writer / Reviewer
- 通信：消息总线 / 共享状态
- **必须**有最终仲裁者（避免无限讨论）

---

## 四、Tool / Function Calling 规范

### 4.1 协议统一

> 所有 provider 均需为**国产模型**，OpenAI 协议块需用 DeepSeek / 通义 / GLM 等 OpenAI 兼容端点。

| Provider | 协议 | LangChain 抽象 | 备注 |
|----------|------|---------------|------|
| **DeepSeek** | OpenAI 兼容 (`/chat/completions`) | `@tool` decorator | 主力，协议标准 |
| **通义千问 (DashScope)** | OpenAI 兼容 + 灵积（DashScope 原生） | `@tool` decorator | 推荐用 OpenAI 兼容模式 |
| **智谱 GLM** | OpenAI 兼容 | `@tool` decorator | 同上 |
| **vLLM (Qwen/DeepSeek)** | OpenAI 兼容 | `@tool` decorator | 本地部署首选 |
| ❌ OpenAI | — | **禁止使用** | 国外 API |
| ❌ Anthropic | — | **禁止使用** | 国外 API |

**强制**：用 LangChain `@tool` 装饰器定义 Tool，跨 provider 自动转换：

```python
from langchain.tools import tool

@tool
def search_documents(query: str, top_k: int = 5) -> list[dict]:
    """在文档库中检索与 query 相关的文档片段。

    Args:
        query: 用户问题的自然语言表达
        top_k: 返回 top-k 条结果，默认 5

    Returns:
        命中文档列表，每条含 text/source/score
    """
    # 实际检索逻辑
    return results
```

### 4.2 Tool Schema 标准

| 要素 | 强制 |
|------|------|
| **docstring 第一段** | 必须一句话说明 Tool 用途（LLM 用此判断何时调用） |
| **Args** | 必须详细描述每个参数（LLM 据此填参） |
| **Returns** | 必须说明返回结构 |
| **Raises** | 必须说明可能抛出的异常（LLM 据此决策） |
| **type hints** | 强制使用（用于 schema 推断） |

### 4.3 Tool 调用超时 / 重试 / 降级

```python
from tenacity import retry, stop_after_attempt, wait_exponential, timeout

@tool
@timeout(30)  # 30 秒超时
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def call_external_api(endpoint: str, params: dict) -> dict:
    """调用外部 API。失败时自动重试 3 次，指数退避。"""
    ...
```

❌ **禁止**：
- Tool 内做长时阻塞 IO（>30s）无超时
- Tool 失败无 fallback（直接抛异常导致 Agent 终止）
- Tool 副作用（写 DB / 发邮件）无幂等保护

---

## 五、Prompt 模板版本管理

### 5.1 Prompt 与代码解耦

**强制**：所有 Prompt 模板必须放在 `prompts/` 目录，**禁止**硬编码在 `.py` 业务代码中。

```
prompts/
├── v1/
│   ├── system.txt
│   ├── rag_query.txt
│   └── router.txt
├── v2/
│   ├── system.txt  # 改了一行，先灰度 v2
│   └── ...
└── active.txt  # 指向当前激活版本（v1 或 v2）
```

加载方式：

```python
from pathlib import Path

def load_prompt(name: str, version: str | None = None) -> str:
    version = version or Path("prompts/active.txt").read_text().strip()
    return Path(f"prompts/{version}/{name}.txt").read_text()
```

### 5.2 Prompt A/B 测试

- 同一 Prompt 的多个版本同时在线，按 `user_id % 100` 路由
- 通过 Langfuse 收集各版本的 faithfulness / user_feedback
- 自动比较，胜出版本逐步扩大流量

### 5.3 Prompt 变更必须联动评估

PR 涉及 Prompt 修改时，CI 必须：
1. 跑 offline eval（固定数据集）
2. 对比基线指标（faithfulness / cost / latency）
3. 指标退化 > 5% 阻断合并

---

## 十四、必须测试的场景清单

- [ ] LLM 输出 JSON 7 步修复管道单元测试
- [ ] Agent Loop max_iterations 兜底测试
- [ ] RAG 召回率 / 准确率评估（详见 [rag-evaluation.md](rag-evaluation.md)）
- [ ] Re-ranking 提升验证
- [ ] 父子分段回溯正确性
- [ ] 元数据过滤（租户 / 权限 / 版本）严格性
- [ ] Token 预算熔断
- [ ] 模型降级链触发
- [ ] Prompt 注入攻击防御
- [ ] PII 检测与脱敏
- [ ] 引用溯源完整性
- [ ] 流式输出中断恢复
- [ ] Langfuse trace 完整覆盖
- [ ] Eval 流水线 CI 集成
- [ ] MCP Tool 被正确发现和调用
- [ ] Skill 触发准确率
- [ ] RAGAS 评测指标计算正确性
- [ ] CI 门禁阈值通过率

---

## 十五、MCP 集成规范（强制）

> 详细规范见 [mcp.md](mcp.md)

### 15.1 核心原则

1. **Tool 暴露必须走 MCP**：新 Tool 优先以 MCP Server 形式暴露，而非直接嵌入 LangChain
2. **Tool 描述必须完整**：每个 MCP Tool 必须有完整的 description + 参数描述
3. **ToolAnnotations 必须声明**：readOnly / destructive / idempotent / openWorld
4. **传输层选型**：本地用 stdio，远程用 Streamable HTTP
5. **集成方式**：使用官方 `langchain-mcp-adapters` 包，**禁止**手写 StructuredTool 转换

### 15.2 MCP Server 开发骨架

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("document-server")

@mcp.tool()
async def search_documents(query: str, top_k: int = 5) -> dict:
    """
    在文档库中检索与 query 相关的文档片段。
    Args:
        query: 用户问题的自然语言表达
        top_k: 返回 top-k 条结果，默认 5
    """
    # 第一步：执行检索
    results = await vector_store.similarity_search(query, k=top_k)

    # 第二步：格式化返回
    return {
        "content": [{"type": "text", "text": f"找到 {len(results)} 条结果"}],
        "structuredContent": {
            "results": [{"text": r.page_content, "source": r.metadata["source"]} for r in results]
        }
    }
```

### 15.3 MCP 与 LangGraph 集成

> **必须使用官方 `langchain-mcp-adapters` 包**，**禁止**手写 StructuredTool 转换。
> 安装：`uv add langchain-mcp-adapters`

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

async with MultiServerMCPClient({
    "document": {"command": "python", "args": ["-m", "doc_server"], "transport": "stdio"},
}) as client:
    tools = client.get_tools()
    agent = create_react_agent(model, tools)
```

---

## 十六、Skill 集成规范（强制）

> 详细规范见 [skill.md](skill.md)

### 16.1 核心原则

1. **领域知识 Skill 化**：复杂业务流程（RAG pipeline、数据处理、代码审查）优先 Skill 化
2. **渐进式披露**：元数据常驻（~100 tokens），正文按需加载（<5000 tokens），资源按需
3. **Action-First**：Skill 内容必须是可执行的代码/流程，而非概念知识
4. **description 必须精心设计**：这是 Agent 触发 Skill 的唯一信号
5. **Gotchas 必须写**：信号密度最高的内容段落

### 16.2 Skill 目录结构示例

```
skills/
├── document-qa/
│   ├── SKILL.md              # QA 流程指令
│   ├── prompts/              # Prompt 模板
│   │   ├── intent.jinja2
│   │   └── generate.jinja2
│   ├── references/
│   │   └── reranking.md      # 重排序策略
│   └── scripts/
│       └── eval_ragas.py     # RAG 评估脚本
```

### 16.3 Skill 与 Agent 工作流集成

```python
class DocumentQASkill:
    """Skill: 文档问答流程"""

    def __init__(self, llm, vector_store, reranker):
        self.llm = llm
        self.vector_store = vector_store
        self.reranker = reranker

    def execute(self, query: str) -> SkillResult:
        # 第一步：意图识别（Skill 指令驱动）
        intent = self._recognize_intent(query)

        # 第二步：查询改写
        rewritten = self._rewrite_query(query, intent)

        # 第三步：检索 + 重排序
        docs = self._retrieve_and_rerank(rewritten)

        # 第四步：验证中间产物
        self._validate_docs(docs)

        # 第五步：生成
        answer = self._generate(query, docs)

        return SkillResult(answer=answer, references=docs)
```

---

## 十七、RAG 评测规范（强制）

> 详细规范见 [rag-evaluation.md](rag-evaluation.md)

### 17.1 核心原则

1. **评测工具选型**：RAG 项目**优先用 RAGAS**（指标更专业），通用 LLM 评测可搭配 DeepEval
2. **必须覆盖的核心指标**：Faithfulness + ContextRecall + FactualCorrectness（最小指标集）
3. **评测 LLM 必须用国产模型**：评估 LLM 配置为 `deepseek-chat`，**禁止使用国外 API**
4. **评测数据集必须版本管理**：golden dataset 纳入 Git，随 Prompt/检索配置变更同步更新
5. **CI 门禁必须配置**：RAG 相关代码变更（`app/services/rag/**`, `prompts/**`）必须跑评测门禁
6. **回归阈值必须设定**：
   - Faithfulness: ≥ 0.85（最低 0.7）
   - Context Recall: ≥ 0.8（最低 0.6）
   - Factual Correctness (F1): ≥ 0.75（最低 0.6）
   - Noise Sensitivity: < 0.15（最高 0.3）

### 17.2 RAG 评测骨架（Collections API）

```python
from ragas.metrics.collections import Faithfulness, ContextRecall, FactualCorrectness
from ragas.llms import llm_factory
from ragas import EvaluationDataset, evaluate

# 第一步：初始化评估 LLM（必须用国产模型）
llm = llm_factory("deepseek-chat")

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
result = evaluate(
    dataset=dataset,
    metrics=[
        Faithfulness(llm=llm),
        ContextRecall(llm=llm),
        FactualCorrectness(llm=llm),
    ],
    llm=llm,
)

# 第四步：验证门禁
THRESHOLDS = {"faithfulness": 0.85, "context_recall": 0.8, "factual_correctness": 0.75}
for metric, threshold in THRESHOLDS.items():
    assert result[metric] >= threshold, f"{metric} {result[metric]:.3f} 低于阈值 {threshold}"
```

### 17.3 评测数据集规范

- 最少 50~100 条样本，覆盖 Single-Hop / Multi-Hop、Specific / Abstract 四类查询
- 人工审核 golden dataset，确保高质量
- 定期从生产日志采样真实 query 补充到评测集（防止数据漂移）

---

## 十八、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **架构** | ❌ 在业务代码中硬编码 LLM provider；❌ 跨 Agent 共享全局可变状态；❌ **使用任何国外 API（OpenAI / Anthropic / Cohere / Jina / OpenRouter）** |
| **检索** | ❌ 不做 RAG 引用溯源；❌ 只用 dense 不用 BM25；❌ Query 不改写直接检索 |
| **Prompt** | ❌ Prompt 模板硬编码在代码里；❌ Prompt 改动不跑 eval 直接上线 |
| **Memory** | ❌ Memory 无 TTL 无限增长；❌ 不提供用户删除 memory 接口 |
| **Trace** | ❌ LLM 调用不打 trace；❌ 敏感信息（API Key / PII）写日志 |
| **安全** | ❌ 用户输入直接拼入 Prompt（注入风险）；❌ 输出不经过滤直返前端 |
| **成本** | ❌ LLM 调用无 max_tokens；❌ 并发无 semaphore；❌ 不监控成本 |
| **可重现** | ❌ 生产用 temperature > 0.7 无 eval；❌ Embedding 升级不重建索引 |
| **降级** | ❌ 所有降级策略都失败仍 500；❌ Tool 调用无 timeout |
| **测试** | ❌ 不写 offline eval；❌ PR 不跑 eval 流水线；❌ 无 fixture 直接调真实 LLM |
| **模型合规** | ❌ 调用 OpenAI / Anthropic 等国外 API；❌ 引入 `openai` / `anthropic` SDK 作为生产依赖；❌ 国产模型降级链兜底缺失 |
| **MCP** | ❌ Tool 无 description 或描述模糊；❌ Tool 无 inputSchema；❌ ToolAnnotations 不声明；❌ stdio 模式 print stdout |
| **Skill** | ❌ Skill 无 description 或描述模糊；❌ SKILL.md 超过 500 行；❌ Knowledge-First 而非 Action-First；❌ 堆 MUST 而不解释 Why |
| **RAG 评测** | ❌ 评测 LLM 使用国外 API；❌ 不设门禁阈值就跑评测；❌ 评测数据集不版本管理；❌ 使用 Legacy API 开始新项目 |
