> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# 多 Agent 协作规范

> 适用场景：多个 Agent 协同完成复杂任务，覆盖 CrewAI / AutoGen / 自研多 Agent 编排。
> 与 [agent.md](agent.md)（§三 Agent Loop）/ [skill.md](skill.md)（Skill 编排）协同。

---

## 一、本质结论

**一句话结论**：多 Agent = 把一个复杂任务拆给多个专业 Agent 分工执行，最终由仲裁者汇总结果。

**核心类比**：
- 单 Agent = 一个全栈工程师做所有事
- 多 Agent = 一个团队，每人专精一块，项目经理（仲裁者）协调

---

## 二、适用场景

| 场景 | 单 Agent | 多 Agent |
|------|---------|---------|
| 简单问答 / 单步检索 | ✅ | ❌ 过度设计 |
| RAG 检索 + 生成 + 校验 | ✅ | 可选 |
| 研究报告 + 数据分析 + 文档生成 | ❌ 单 Agent 难以胜任 | ✅ |
| 代码审查 + 测试 + 重构建议 | ❌ | ✅ |
| 多轮对话 + 外部工具 + 审批流程 | ❌ | ✅ |

---

## 三、CrewAI 模式（推荐：角色扮演型）

### 3.1 核心概念

| 概念 | 说明 |
|------|------|
| **Agent** | 带角色、目标、工具的独立 AI |
| **Task** | 分配给 Agent 的具体任务 |
| **Crew** | Agent + Task 的编排容器 |
| **Process** | 任务执行模式（顺序 / 层级） |

### 3.2 标准模板

```python
from crewai import Agent, Task, Crew

# 第一步：定义 Agent（带角色和工具）
researcher = Agent(
    role="研究员",
    goal="收集并分析相关资料",
    backstory="你是一位资深研究员，擅长从大量文档中提取关键信息",
    tools=[search_tool, read_tool],
    llm=llm,
)

writer = Agent(
    role="撰稿人",
    goal="根据研究结果撰写报告",
    backstory="你是一位专业撰稿人，擅长将复杂信息转化为清晰的文档",
    llm=llm,
)

# 第二步：定义 Task
research_task = Task(
    description="调研 {topic} 的最新进展，输出要点清单",
    expected_output="包含 5-10 个关键要点的清单，每点带来源引用",
    agent=researcher,
)

writing_task = Task(
    description="根据研究结果撰写结构化报告",
    expected_output="包含摘要、要点分析、结论的 Markdown 报告",
    agent=writer,
    context=[research_task],  # 依赖研究任务的结果
)

# 第三步：编排执行
crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, writing_task],
    process="sequential",  # 顺序执行：研究 → 撰写
)

result = crew.kickoff(inputs={"topic": "RAG 技术进展"})
```

---

## 四、AutoGen 模式（推荐：对话协商型）

```python
from autogen import AssistantAgent, UserProxyAgent

# 第一步：定义 Agent
analyst = AssistantAgent(
    name="数据分析师",
    system_message="你是数据分析专家，擅长从数据中发现规律和洞察",
    llm_config={"model": "deepseek-chat"},
)

reviewer = AssistantAgent(
    name="审核员",
    system_message="你是数据审核专家，负责检查分析结论的正确性",
    llm_config={"model": "deepseek-chat"},
)

user_proxy = UserProxyAgent(
    name="用户",
    human_input_mode="NEVER",  # 自动模式，不需人工输入
    max_consecutive_auto_reply=5,  # 防止无限对话
)

# 第二步：启动多轮对话
user_proxy.initiate_chat(
    analyst,
    message="分析以下销售数据的趋势...",
)
```

---

## 五、仲裁者设计（强制）

**强制**：多 Agent 系统**必须**有最终仲裁者，防止无限讨论。

### 5.1 仲裁策略

| 策略 | 适用场景 |
|------|---------|
| **投票多数** | 3+ Agent 各自独立判断，取多数意见 |
| **等级优先** | 高权限 Agent 的决策覆盖低权限 |
| **LLM-as-Judge** | 用独立 LLM 评估各 Agent 输出质量，选最优 |
| **规则兜底** | 业务规则硬约束（如审批流最终由人类拍板） |

### 5.2 超时与轮次限制

```python
MAX_ROUNDS = 5  # 最多讨论 5 轮
MAX_TIME = 120  # 最多 120 秒

if round_count > MAX_ROUNDS:
    # 由仲裁者直接给出结论
    return arbiter.decide(results)
```

---

## 六、Agent 间通信规范

| 方式 | 适用场景 | 优缺点 |
|------|---------|--------|
| **消息传递** | 简单协作 | 简单直接，但上下文断裂 |
| **共享状态** | 紧耦合协作 | 上下文完整，但需同步机制 |
| **事件总线** | 松耦合协作 | 解耦好，但调试困难 |

**推荐**：LangGraph 共享 State 作为 Agent 间通信的默认方式。

---

## 七、禁止事项

| 类别 | 禁止 |
|------|------|
| **设计** | ❌ 简单任务用多 Agent（过度设计）；❌ 无仲裁者的多 Agent 系统 |
| **通信** | ❌ Agent 间传递敏感信息（API Key / PII）；❌ 共享全局可变状态 |
| **执行** | ❌ 无限轮次讨论；❌ 无超时限制；❌ 无日志追踪 |
| **模型合规** | ❌ 多 Agent 中混用国外和国产模型；❌ 所有 Agent 用同一模型（无多样性） |
| **成本** | ❌ 不监控多 Agent 总 token 消耗；❌ 每轮都传全量上下文 |
