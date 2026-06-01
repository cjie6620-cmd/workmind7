> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Prompt Engineering 规范

> 适用场景：设计/优化 Prompt 模板、Few-shot 示例设计、RAG 场景 Prompt 优化。
>
> 本文件是 Python + FastAPI + Agent + RAG 项目的 **Prompt 工程核心规范**，与 [agent.md](agent.md) 形成「网状约束」。

---

## 一、本质结论

**一句话结论**：Prompt = 给 LLM 的"任务说明书"。好的 Prompt 让模型稳定输出正确结果。

**核心类比**：
- Prompt = 程序员的代码
- 模型 = 编译器
- 输出 = 运行结果

**关键点**：
1. Prompt 是 LLM 应用的核心资产，必须版本化管理
2. 好的 Prompt 让模型"知道该做什么"，而不是"猜你在想什么"
3. Prompt 优化是数据驱动的迭代过程，不是拍脑袋

---

## 二、10 条核心设计原则（OpenAI/Anthropic/Google 三家共识）

### P1. 清晰明确，不要假设模型知道你的意图

**本质**：把模型当成"聪明但什么都不知道的新员工"

**关键点**：
- 用具体数字、格式要求、边界条件替代模糊描述
- **测试方法**：把 Prompt 给不了解任务的同事看，如果他看不懂，模型也看不懂

**❌ 错误示例**：
```
帮我分析一下这个数据
```

**✅ 正确示例**：
```
分析以下销售数据，输出 top 5 产品、同比增长率、异常值，用表格格式
```

---

### P2. 结构化 Prompt（Markdown + XML 标签分隔）

**本质**：用层次结构让模型理解 Prompt 边界

**关键点**：
- 用 Markdown 标题（`# Identity` / `# Instructions` / `# Examples` / `# Context`）划分层次
- 用 XML 标签包裹数据块（`<context>...</context>`、`<examples>...</examples>`）
- 三家厂商一致推荐此格式

**✅ 正确示例**：
```
# Identity
你是企业知识库问答助手。

# Instructions
- 仅基于 <context> 中的信息回答
- 如果上下文不包含答案，明确说"根据现有资料无法回答"
- 引用时标注来源：[文档名, 页码/段落]

<context>
{retrieved_chunks}
</context>

<user_query>
{user_question}
</user_query>
```

---

### P3. 角色设定（System Prompt / Developer Message）

**本质**：第一句话定义身份和行为边界

**关键点**：
- OpenAI: `developer` > `user` > `assistant` 的优先级体系
- Anthropic: system prompt 定义角色
- Google: system instruction 设置

**✅ 正确示例**：
```
你是一个专业的客服助手，专注于解答产品使用问题。
你的回答必须：
1. 简洁明了，控制在 100 字以内
2. 使用友好专业的语气
3. 如果不确定，直接说"我需要转接人工客服"
```

---

### P4. Few-shot 比 Zero-shot 效果好得多

**本质**：给模型看"正确答案长什么样"

**关键点**：
- Google 原话："我们推荐始终包含 few-shot examples"
- 3-5 个多样化的例子效果最佳
- 例子格式必须一致（XML 标签、换行、分隔符全部对齐）
- 例子太多会过拟合，需要实验找到最优数量

**❌ 错误示例**：
```
# 无例子，只给指令
输出 JSON 格式
```

**✅ 正确示例**：
```
# 有例子，格式严格一致
<examples>
<example>
<input>苹果 iPhone 15</input>
<output>{"product": "iPhone 15", "brand": "Apple", "category": "手机"}</output>
</example>
<example>
<input>华为 Mate 60</input>
<output>{"product": "Mate 60", "brand": "华为", "category": "手机"}</output>
</example>
</examples>

<input>{user_input}</input>
```

---

### P5. 让模型先思考再回答（Chain of Thought）

**本质**：复杂任务需要推理步骤

**关键点**：
- 推理模型（o 系列 / Gemini thinking）：不需要手动 CoT，模型自动内部思考
- 非推理模型（DeepSeek-chat）：手动添加 "Let's think step by step" 或要求模型先列出推理步骤
- Anthropic: "Let Claude think (CoT)" 是 9 大技术中排第 4 的核心技术

**✅ 正确示例**：
```
请按照以下步骤分析：

1. 首先，识别用户的核心问题
2. 然后，从上下文中找到相关证据
3. 接着，评估证据的可信度
4. 最后，给出结论并标注引用来源

用户问题：{user_question}
上下文：{context}
```

---

### P6. 正面指令优于负面指令

**本质**：告诉模型"做什么"，而不是"不做什么"

**❌ 错误示例**：
```
不要使用 Markdown，不要超过 100 字，不要用专业术语
```

**✅ 正确示例**：
```
用纯文本回答，控制在 80-100 字，面向非技术用户
```

---

### P7. 提供上下文和动机

**本质**：解释"为什么"比只说"做什么"效果更好

**关键点**：
- 告诉模型：任务结果的用途、目标受众、在工作流中的位置
- Google Gemini 3: 在长上下文场景中，先放数据，指令放最后，用 "Based on the above..." 衔接

**✅ 正确示例**：
```
这份报告将提交给公司高层，用于战略决策。
因此，你需要：
1. 提炼核心洞察，不要堆砌细节
2. 用数据支撑结论
3. 给出明确的行动建议
```

---

### P8. 控制输出格式要显式指定

**本质**：不要让模型猜你想要什么格式

**关键点**：
- 需要 JSON 输出：使用 Structured Outputs / JSON Schema
- 需要特定格式：在 Prompt 中用例子展示目标格式，或用 completion 策略
- 需要简洁/详细：明确告诉模型

**✅ 正确示例**：
```
请严格按照以下 JSON Schema 输出：
{
  "product_name": "string",
  "price": "number",
  "in_stock": "boolean"
}

注意：
- 所有字段必须存在
- 价格保留两位小数
- 库存状态用 true/false
```

---

### P9. Prompt 文件化管理，纳入版本控制

**本质**：Prompt 是核心资产，必须规范管理

**强制要求**：
- Prompt **必须**以文件形式存储（`.txt` / `.jinja2` / `.yaml`），**禁止**硬编码在 Python 代码中
- 统一放在 `prompts/` 或 `app/prompts/` 目录，按业务域命名：`{domain}-{action}-prompt.txt`
- 使用 Jinja2 模板语法注入变量：`{{ user_query }}`，禁止 f-string 拼接
- 修改 Prompt 必须在 commit message 中说明变更原因
- 重大 Prompt 变更需 A/B 测试验证效果后再上线

**❌ 错误示例**：
```python
# Prompt 硬编码在代码中
prompt = f"你是{role}助手，请回答{question}"
```

**✅ 正确示例**：
```python
# Prompt 存为模板文件
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('prompts'))
template = env.get_template('qa-prompt.jinja2')
prompt = template.render(role="客服", question=user_question)
```

---

### P10. 建立评估体系（Evals），用数据驱动 Prompt 迭代

**本质**：用数据验证 Prompt 效果，而不是"感觉还行"

**关键点**：
- OpenAI: "Build evals that measure the behavior of your prompts"
- Anthropic: Prompt engineering 前提是 "有清晰的成功标准 + 有经验性测试方法"
- 迭代方法：换措辞、换任务类比、调顺序、调温度
- 用 golden dataset（固定输入 -> 期望输出）做回归测试

**强制要求**：
- PR 涉及 Prompt 修改时，CI 必须跑 offline eval
- 对比基线指标（faithfulness / cost / latency）
- 指标退化 > 5% 阻断合并

---

## 三、10 种常用 Prompt 模式

### 1. Zero-shot（零样本）

**场景**: 简单分类、翻译、摘要等任务

**特点**: 不给例子，只给指令

**适用**: 模型能力强（DeepSeek-chat / qwen-max）时够用

**示例**：
```
将以下英文翻译成中文：
{english_text}
```

---

### 2. Few-shot（少样本）

**场景**: 格式控制、特定领域任务、输出规范化

**做法**: 在 Prompt 中给出 3-5 个 input -> output 对

**关键**: 例子要多样化，格式严格一致

**示例**：
```
<examples>
<example>
<query>退款流程是什么？</query>
<answer>根据公司政策，退款流程如下：1. 提交退款申请；2. 客服审核；3. 退款到账（3-5个工作日）。</answer>
</example>
<example>
<query>如何修改密码？</query>
<answer>修改密码步骤：1. 登录账号；2. 进入"个人设置"；3. 点击"修改密码"；4. 输入旧密码和新密码；5. 确认修改。</answer>
</example>
</examples>

<query>{user_query}</query>
```

---

### 3. Chain of Thought (CoT)

**场景**: 数学推理、逻辑分析、多步骤决策

**做法**: 添加 "Let's think step by step" 或要求模型先输出推理过程

**进阶**: Self-consistency（多次采样取多数答案）

**示例**：
```
请逐步分析以下问题：

问题：{user_question}

分析步骤：
1. 首先，明确问题的核心是什么
2. 然后，从上下文中找到相关信息
3. 接着，评估信息的可信度和相关性
4. 最后，给出结论

请按照这个步骤输出你的分析过程。
```

---

### 4. ReAct（Reasoning + Acting）

**场景**: Agent 场景、工具调用、信息检索

**做法**: 模型交替输出 Thought / Action / Observation

**典型用法**: LangChain Agent 中的标准模式

**示例**：
```
请按照以下格式回答：

Question: {user_question}
Thought: 我需要先理解用户的问题，然后决定使用什么工具
Action: search_documents
Action Input: {"query": "用户问题的关键词"}
Observation: [检索结果]
Thought: 根据检索结果，我可以回答用户的问题了
Final Answer: [最终答案]
```

---

### 5. Structured Output Prompting

**场景**: API 返回 JSON、数据提取、表单填写

**做法**:
- OpenAI: 使用 `response_format: { type: "json_schema" }` 参数
- Anthropic: XML 标签 + 偏好系统指令
- 国产模型: few-shot + completion 策略

**示例**：
```
请从以下文本中提取产品信息，输出 JSON 格式：

文本：{product_description}

输出格式：
{
  "product_name": "string",
  "brand": "string",
  "price": "number",
  "features": ["string"]
}

示例：
输入：iPhone 15 是苹果公司推出的手机，售价 7999 元，支持 5G 和 Face ID
输出：{"product_name": "iPhone 15", "brand": "苹果", "price": 7999, "features": ["5G", "Face ID"]}
```

---

### 6. RAG Prompt（检索增强生成）

**场景**: 知识库问答、文档搜索、企业内部助手

**做法**:
- 将检索到的文档块放在 `<context>` 标签中
- 指令中明确告诉模型 "仅基于提供的上下文回答"
- 如果上下文中没有答案，要求模型说"我不确定"
- 要求模型给出引用来源（行号/段落/文档名）

**示例**：
```
# Role
你是企业知识库问答助手。

# Instructions
- 仅基于 <context> 中的信息回答
- 如果上下文不包含答案，明确说"根据现有资料无法回答"
- 引用时标注来源：[文档名, 页码/段落]
- 保持回答简洁，控制在 200 字以内

<context>
{retrieved_chunks}
</context>

<user_query>
{user_question}
</user_query>
```

---

### 7. Role-based Prompting（角色扮演）

**场景**: 客服、教育、专业领域问答

**做法**: 在 system prompt 中定义角色、专业领域、行为规则

**Claude 4 建议**: 角色设定 + 行为规则 + 输出格式，三合一

**示例**：
```
# Role
你是一位资深的 Python 后端工程师，专注于 FastAPI 和 SQLAlchemy。

# Behavior Rules
1. 代码必须符合 PEP 8 规范
2. 所有函数必须有类型注解
3. 关键逻辑必须有注释
4. 优先使用异步编程

# Output Format
- 代码用 markdown 代码块包裹
- 必须包含完整的 import 语句
- 关键设计点用注释说明
```

---

### 8. Prompt Chaining（Prompt 链）

**场景**: 复杂多步骤任务

**做法**: 将任务拆成多个独立 Prompt，前一步输出作为后一步输入

**Google 三种模式**:
- 分解指令: 一个 Prompt 一个指令
- 链式调用: 输出串联
- 聚合模式: 并行处理不同数据块，最后合并

**示例**：
```
# Step 1: 提取关键词
请从用户问题中提取 3-5 个关键词，用逗号分隔。
用户问题：{user_question}

# Step 2: 检索文档
根据以下关键词检索相关文档：
关键词：{keywords_from_step1}

# Step 3: 生成答案
根据检索到的文档回答用户问题：
用户问题：{user_question}
文档：{documents_from_step2}
```

---

### 9. Prefill / Completion Strategy（预填充）

**场景**: 控制输出格式、强制输出结构

**做法**: 给出输出的开头部分，让模型续写

**典型**: 给出 `{"` 让模型生成 JSON 键值

**示例**：
```
请分析以下产品评价，输出情感分析结果：

评价：{product_review}

输出格式：
{
  "sentiment": "
```

模型会续写：`positive"` 或 `negative"`

---

### 10. Agentic Workflow Prompting

**场景**: Agent 自主执行、工具调用、长期任务

**做法**: 逻辑依赖分析 -> 风险评估 -> 假设探索 -> 结果评估 -> 适应性调整 -> 完整性校验

**示例**：
```
你是一个自主执行任务的 Agent。请按照以下流程处理用户请求：

1. **任务分析**：理解用户的核心需求
2. **工具选择**：决定使用哪些工具（search_documents / query_database / call_api）
3. **执行计划**：列出执行步骤和依赖关系
4. **风险评估**：识别可能的失败点和应对策略
5. **执行监控**：跟踪执行进度，记录中间结果
6. **结果验证**：检查输出是否符合预期
7. **异常处理**：如果失败，尝试降级方案

用户请求：{user_request}
可用工具：{available_tools}
```

---

## 四、RAG 场景 Prompt 优化要点

### 4.1 检索前（Query 改写）

**场景**: 用户原始问题 -> LLM 改写为结构化查询

**策略**: 简洁化 / 抽象化 / 纠错 / 多语言标准化

**Prompt 示例**：
```
你是一个查询改写助手。将用户的口语化问题改写为适合向量检索的简洁查询。

要求：
1. 去除口语化表达（"那个"、"就是"、"嘛"）
2. 纠正错别字
3. 保留核心实体和意图
4. 控制在 15 字以内

只输出改写后的查询，不要解释。

用户问题：{user_query}
```

---

### 4.2 检索后（上下文注入）

**场景**: 将检索结果用 XML 标签包裹，与用户问题明确分隔

**Prompt 结构**：
```
# Role
你是 [领域] 专家助手。

# Instructions
- 仅基于 <context> 中的信息回答
- 如果上下文不包含答案，明确说"根据现有资料无法回答"
- 引用时标注来源：[文档名, 页码/段落]
- 保持回答简洁，控制在 200 字以内

<context>
{retrieved_chunks}
</context>

<user_query>
{user_question}
</user_query>
```

---

### 4.3 减少幻觉

**关键策略**：
1. 强制要求引用来源
2. 设定 "不知道就说不知道" 的行为
3. 提供 confidence score 指令
4. 使用 Structured Output 让模型输出 `{ answer, sources, confidence }`

**示例**：
```
请根据上下文回答问题，并按照以下格式输出：

{
  "answer": "你的回答",
  "sources": ["来源1", "来源2"],
  "confidence": 0.95
}

注意：
- 如果上下文不包含答案，answer 设为 "根据现有资料无法回答"
- sources 必须引用上下文中的具体文档
- confidence 根据上下文相关性给出 0-1 的分数
```

---

### 4.4 长上下文优化

**关键策略**：
1. 重要指令放 Prompt 开头和结尾（首因效应 + 近因效应）
2. Google Gemini 3: 数据在前，指令在后
3. 用 "Based on the information above..." 做上下文锚定
4. Anthropic: 避免在上下文中间放关键指令

**示例**：
```
# Instructions（放在开头）
请基于以下文档回答问题。仅使用文档中的信息，不要添加任何外部知识。

# Context（数据在前）
{long_context}

# Anchor（上下文锚定）
Based on the above documents, please answer the following question:

# Question（指令在后）
{user_question}

# Reminder（指令重复）
Remember: Only use information from the provided documents. If the answer is not in the documents, say "I cannot find the answer in the provided documents."
```

---

## 五、10 大反模式（应该避免什么）

### AP1. 模糊指令

**❌ 错误**：
```
帮我分析一下这个数据
```

**✅ 正确**：
```
分析以下销售数据，输出 top 5 产品、同比增长率、异常值，用表格格式
```

---

### AP2. 没有例子的格式控制

**❌ 错误**：
```
输出 JSON 格式
```

**✅ 正确**：
```
输出 JSON 格式，示例：
{"product": "iPhone 15", "price": 7999}
```

---

### AP3. 一次性堆砌大量指令

**❌ 错误**：
```
一个 Prompt 20 条规则
```

**✅ 正确**：
```
拆分为多个步骤，用 Prompt Chain 处理
```

---

### AP4. 负面指令过多

**❌ 错误**：
```
不要用 Markdown，不要超过 100 字，不要用专业术语
```

**✅ 正确**：
```
用纯文本回答，控制在 80-100 字，面向非技术用户
```

---

### AP5. RAG 中假设模型知道答案

**❌ 错误**：
```
不提供上下文就问 "我们的退款政策是什么？"
```

**✅ 正确**：
```
检索相关文档 -> 注入 <context> -> 再提问
```

---

### AP6. Prompt 硬编码在代码中

**❌ 错误**：
```python
prompt = f"你是{role}助手，请回答{question}"
```

**✅ 正确**：
```python
# Prompt 存为模板文件
template = env.get_template('qa-prompt.jinja2')
prompt = template.render(role="客服", question=user_question)
```

---

### AP7. 不测试就上线

**❌ 错误**：
```
写完 Prompt 直接部署
```

**✅ 正确**：
```
用 golden dataset 做回归测试，量化评估后再上线
```

---

### AP8. 忽略模型差异

**❌ 错误**：
```
同一套 Prompt 用于推理模型和非推理模型
```

**✅ 正确**：
```
- 推理模型（o 系列 / Gemini thinking）：给高层目标，信任模型自主规划
- 非推理模型（DeepSeek-chat）：给精确指令，逐步引导
```

---

### AP9. Few-shot 例子不一致

**❌ 错误**：
```
第一个例子输出 "Positive"，第二个输出 "The sentiment is: Negative"
```

**✅ 正确**：
```
所有例子格式严格对齐
```

---

### AP10. 不设 fallback 和边界条件

**❌ 错误**：
```
不处理模型输出超长、格式错误、安全触发等情况
```

**✅ 正确**：
```
加入输出长度约束、格式校验、安全兜底指令
```

---

## 六、国产模型（DeepSeek 等）适配建议

基于三大厂商共识原则，适配国产模型时的关键建议：

### 1. 结构化格式

**推荐**：优先使用 XML 标签分隔（`<role>` / `<context>` / `<examples>`），国产模型对 XML 解析能力普遍较好

### 2. Few-shot 必加

**原因**：国产模型在 zero-shot 下表现波动较大，加 3-5 个例子可显著稳定输出

### 3. 显式 CoT

**关键**：DeepSeek-chat 不是推理模型，需要手动要求 "请先分析再回答"

### 4. Structured Output

**策略**：国产模型暂无原生 JSON Schema 约束，需用 few-shot + completion 策略

### 5. RAG Grounding

**推荐**：使用与 Google 类似的严格 grounding 指令，强制模型仅基于上下文回答

### 6. 温度设置

**建议**：
- 代码/结构化任务：`temperature=0`
- 创意任务：`temperature=0.7-1.0`

### 7. Prompt 长度

**注意**：国产模型上下文窗口有限（DeepSeek-chat 64K），避免注入过多无关上下文

---

## 七、必须测试的场景清单

- [ ] Prompt 模板变量注入正确性
- [ ] Few-shot 例子格式一致性
- [ ] 输出格式符合预期（JSON / 表格 / 纯文本）
- [ ] 长上下文场景下指令不被淹没
- [ ] 国产模型适配性（DeepSeek / 通义千问 / 智谱 GLM）
- [ ] 幻觉率（Faithfulness 指标）
- [ ] 边界条件处理（空输入 / 超长输入 / 恶意输入）
- [ ] A/B 测试结果对比
- [ ] Prompt 版本回滚能力
- [ ] CI 评测门禁通过率

---

## 八、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **存储** | ❌ Prompt 硬编码在 Python 代码中；❌ 使用 f-string 拼接变量（必须用 Jinja2） |
| **管理** | ❌ Prompt 不纳入 Git 版本控制；❌ 修改 Prompt 不在 commit message 中说明原因 |
| **测试** | ❌ Prompt 变更不跑 eval 直接上线；❌ 无 golden dataset 做回归测试 |
| **格式** | ❌ 无例子的格式控制；❌ Few-shot 例子格式不一致 |
| **指令** | ❌ 模糊指令；❌ 负面指令过多；❌ 一次性堆砌 20+ 条规则 |
| **RAG** | ❌ RAG Prompt 不提供上下文；❌ 不强制要求引用来源 |
| **模型** | ❌ 忽略模型差异（推理模型 vs 非推理模型）；❌ 不适配国产模型特性 |
| **安全** | ❌ 用户输入直接拼入 Prompt（注入风险）；❌ Prompt 中暴露系统架构 |

---

## 九、参考资源

> **参考资源集中管理，见** [CLAUDE.md §参考资源索引](../../CLAUDE.md#参考资源索引集中管理不重复)

---

## 十、与其他角色的协作

- **与 [agent.md](agent.md) 的关系**：Prompt 模板版本管理参考 agent.md §五
- **与 [rag-evaluation.md](rag-evaluation.md) 的关系**：Prompt 优化效果必须通过 RAG 评测验证
- **与 [skill.md](skill.md) 的关系**：Skill 中的 Prompt 也必须遵循本规范

---

**最后更新**：2026-06-01
**维护者**：AI Agent
