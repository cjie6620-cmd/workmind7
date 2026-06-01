> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：LangChain 1.0+ / LangGraph 1.0.8+
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# Skill 系统规范

> 适用场景：创建 Skill、优化 Skill 触发、Skill 与 Agent 工作流集成。
>
> 本文件是 Python + FastAPI + Agent + RAG 项目的 **Skill 系统核心规范**，与 [agent.md](agent.md) 形成「网状约束」。

---

## 一、本质结论

**一句话结论**：Skill = 给 AI Agent 注入领域专精能力的标准化知识包。

**核心类比**：
- **Tool** = Agent 的"手"（执行具体操作，如搜索、写文件）
- **Skill** = Agent 的"脑中的专业知识"（知道在什么场景下该怎么做）
- **Plugin** = Skill 的"安装包"（包含 Skill + Hook + MCP + 配置）

**关键点**：
1. Agent 天生聪明但缺乏领域上下文，Skill 就是一份"操作手册"
2. Skill 不是 Tool，Skill 编排多个 Tool 完成复杂任务
3. Skill 的核心价值是 Action-First（给可执行代码），不是 Knowledge-First（教概念）

---

## 二、核心设计原则

### 2.1 渐进式披露 (Progressive Disclosure) -- 最重要

**本质**：Skill 采用三级加载机制，严格控制上下文占用

| 层级 | 内容 | Token 开销 | 何时加载 |
|------|------|-----------|----------|
| **L1 元数据** | name + description | ~100 tokens | 启动时，所有 Skill 都加载 |
| **L2 指令** | SKILL.md 正文 | <5000 tokens | Skill 被触发时 |
| **L3 资源** | scripts/ / references/ / assets/ | 按需 | 执行时按需读取 |

**原则**：上下文窗口是公共资源，每个 Skill 只占用最小必要空间。

---

### 2.2 Action-First，不是 Knowledge-First

**本质**：最有价值的 Skill 是给 Agent **可组合执行的代码**，而不是概念知识

**❌ 错误示例**：
```markdown
## RAG 介绍
RAG（检索增强生成）是一种结合检索和生成的 AI 技术...
（教 Agent "什么是 RAG"）
```

**✅ 正确示例**：
```markdown
## 如何用 pdfplumber 提取 PDF 文本
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        print(text)
```
（教 Agent "如何用 pdfplumber 提取 PDF 文本"）
```

---

### 2.3 Explain the Why，不要堆 MUST

**本质**：现代 LLM 有很强的推理能力，解释"为什么"比强制命令更有效

**❌ 错误示例**：
```markdown
MUST filter test accounts. NEVER skip this step.
```

**✅ 正确示例**：
```markdown
Test accounts inflate metrics by 15-30%, leading to wrong business decisions. 
Always filter them in production queries.
```

---

### 2.4 简洁为王 (Concise is Key)

**强制**：
- SKILL.md 正文 < 500 行
- 只写 Agent 不知道的东西（Agent 已经很聪明）
- 每个 token 都有成本，挑战每段文字："Agent 真的需要这个解释吗？"

---

### 2.5 可验证中间产物

**原则**：复杂任务必须有验证步骤

**示例**：
```
分析 → 生成计划文件 → 验证计划 → 执行 → 验证结果
```

---

## 三、Skill 的生命周期

### 3.1 定义 (Definition)

**目录结构**：
```
skill-name/
├── SKILL.md          # 必需：指令 + 元数据
├── scripts/          # 可选：可执行脚本
├── references/       # 可选：参考文档
└── assets/           # 可选：模板、资源文件
```

---

### 3.2 发现 (Discovery)

Agent 启动时扫描配置目录，只解析 YAML frontmatter：

```
扫描目录 → 找到 SKILL.md → 解析 frontmatter → 提取 name + description → 注入系统提示
```

**系统提示中的格式**：
```xml
<available_skills>
  <skill>
    <name>pdf-processing</name>
    <description>Extract text and tables from PDF files...</description>
    <location>/path/to/skills/pdf-processing/SKILL.md</location>
  </skill>
</available_skills>
```

---

### 3.3 触发 (Triggering)

**触发机制**：Agent 根据 description 字段决定是否激活 Skill，而不是关键词匹配。

**关键洞察**：
- Agent 只对"需要 Skill 才能做好的复杂任务"触发 Skill
- 简单任务（如"读个文件"）即使 description 完美匹配也不会触发
- description 是唯一的触发信号，必须精心设计

**触发描述最佳写法**：

```markdown
# ✅ 好：具体 + 场景覆盖 + "稍微 pushy"
description: >
  Extract text and tables from PDF files, fill forms, merge documents. 
  Use when working with PDF files, when the user mentions PDFs, forms, 
  or document extraction, or when any .pdf file is referenced.

# ❌ 差：太模糊
description: Helps with PDFs.
```

---

### 3.4 执行 (Execution)

```
触发匹配 → 加载 SKILL.md 全文 → 按指令执行 → 按需读取 references/ → 按需执行 scripts/
```

**脚本执行方式**：
```bash
# 执行脚本（不加载内容到上下文，只消耗输出的 token）
python scripts/analyze_form.py input.pdf

# 读取参考文档（加载到上下文）
cat references/finance.md
```

---

## 四、SKILL.md 结构

**标准结构**：

```markdown
---
name: pdf-processing           # 必需，64字符内，小写+连字符
description: Extract text...   # 必需，1024字符内，说明做什么+何时触发
license: Apache-2.0            # 可选
compatibility: Requires git    # 可选，500字符内
allowed-tools: Bash(git:*)     # 可选，预授权工具列表
metadata:                      # 可选，自定义键值对
  author: my-org
  version: "1.0"
---

# Skill Title

## When to use this skill
...

## How to do it
Step-by-step instructions...

## Gotchas (陷阱/易错点)
...（Anthropic 内部数据：这是信号最高的内容段）

## Examples
Input/Output pairs...
```

---

## 五、Skill 与 Tool 的区别和联系

| 维度 | Tool | Skill |
|------|------|-------|
| **抽象层级** | 原子操作 | 领域知识 + 流程编排 |
| **实现形式** | 函数/API 调用 | SKILL.md + 资源文件 |
| **触发方式** | Agent 直接调用 | Agent 根据 description 判断后加载 |
| **上下文影响** | 输入输出占 token | 元数据常驻，正文按需加载 |
| **可组合性** | Skill 内部组合多个 Tool | Tool 被 Skill 编排使用 |
| **例子** | `Read`, `Bash`, `Grep` | `pdf-processing`, `code-review` |

**关系**：Skill 是 Tool 的"高级编排器"。一个 Skill 可以组合多个 Tool 完成复杂任务。

---

## 六、高质量 Skill 的 Checklist

### 核心质量

- [ ] Description 具体，包含关键词
- [ ] Description 说明"做什么"和"何时触发"
- [ ] SKILL.md 正文 < 500 行
- [ ] 详细内容拆分到独立文件
- [ ] 无时效敏感信息
- [ ] 术语全篇一致
- [ ] 示例具体，非抽象
- [ ] 文件引用深度 ≤ 1 层
- [ ] 渐进式披露合理使用
- [ ] 工作流步骤清晰

### 代码和脚本

- [ ] 脚本解决问题，不把问题推给 Agent
- [ ] 错误处理明确且有帮助
- [ ] 无魔法数字（所有值有注释说明）
- [ ] 依赖包在指令中列出
- [ ] 无 Windows 风格路径（全用 `/`）
- [ ] 关键操作有验证步骤
- [ ] 质量关键任务有反馈循环

### 测试

- [ ] 至少 3 个评估场景
- [ ] 在目标模型上测试过
- [ ] 用真实场景测试
- [ ] 收集了团队反馈

---

## 七、Gotchas 段落（信号最高）

**Anthropic 内部数据**：Gotchas 是 Skill 中信号密度最高的段落。

**示例**：
```markdown
## Gotchas

1. **Don't compress tool definitions** — models need exact schemas
2. **Sub-agents sharing context via message passing** doubles token cost vs filesystem coordination
3. **Prefix caching breaks** when system prompts change between turns
4. **Batch operations must validate** before applying — partial writes corrupt data
```

---

## 八、反馈循环模式

**示例**：
```markdown
## Document editing process

1. Make your edits
2. **Validate immediately**: `python scripts/validate.py`
3. If validation fails:
   - Review the error message
   - Fix the issues
   - Run validation again
4. **Only proceed when validation passes**
5. Rebuild and test
```

---

## 九、Skill 的九大类别（Anthropic 内部分类）

| 类别 | 说明 | 例子 |
|------|------|------|
| **验证 (Verification)** | 检查输出质量 | `verification-before-completion` |
| **脚手架 (Scaffolding)** | 生成项目骨架 | `mcp-builder` |
| **自动化 (Automation)** | 自动化重复任务 | `slack-gif-creator` |
| **运行手册 (Runbook)** | 故障排查流程 | `systematic-debugging` |
| **部署 (Deployment)** | 部署和运维 | `devops` Skill |
| **领域专精 (Domain)** | 特定领域知识 | `pdf`, `docx`, `xlsx` |
| **流程编排 (Workflow)** | 多步骤工作流 | `test-driven-development` |
| **元技能 (Meta)** | 创建 Skill 的 Skill | `skill-creator` |
| **集成 (Integration)** | 外部服务集成 | `claude-api`, `mcp-builder` |

---

## 十、Skill 与 Agent 工作流的集成模式

### 10.1 Skill 调用 Skill（组合模式）

**示例**：
```markdown
# 在 code-review Skill 中
## Review workflow
1. Use `systematic-debugging` skill for investigating issues
2. Use `test-driven-development` skill for writing regression tests
3. Compile findings into review report
```

---

### 10.2 Skill + MCP Tool 集成

**示例**：
```markdown
## 使用 MCP 工具时，必须用全限定名
Use the BigQuery:bigquery_schema tool to retrieve table schemas.
Use the GitHub:create_issue tool to create issues.
```

---

### 10.3 Skill + Subagent 模式

**示例**：
```markdown
## Parallel execution
1. Spawn subagent A with `pdf-processing` skill for document extraction
2. Spawn subagent B with `data-analysis` skill for data processing
3. Merge results in main agent
```

---

### 10.4 Skill + Hook 联动

**示例**：
```markdown
# Skill 可通过 Hook 实现按需守卫
# 例如：/careful 激活时，阻止破坏性命令
# 例如：/freeze 激活时，阻止目录外编辑
```

---

## 十一、2024-2025 主流 Agent 框架中的 Skill/Tool 设计模式

### 11.1 Claude Code Skill（当前最成熟）

- 开放标准，已被 Cursor、Amp、VS Code、GitHub Copilot 等采纳
- 文件系统即接口：SKILL.md + 目录结构
- 渐进式披露：元数据 → 正文 → 资源

---

### 11.2 LangChain Tool / LangGraph ToolNode

```python
# Tool 是函数级抽象
@tool
def search_documents(query: str, top_k: int = 5) -> list[dict]:
    """Search documents by semantic similarity."""
    ...

# LangGraph 中 Tool 作为节点
graph.add_node("tools", ToolNode([search_documents, ...]))
```

- Tool = 函数签名 + docstring
- Skill ≈ 多个 Tool 的编排 + Prompt 模板

---

### 11.3 OpenAI Function Calling / Custom GPTs

- Function = JSON Schema 定义的工具
- Custom GPT Instructions ≈ 简化版 Skill（System Prompt + Knowledge Files）

---

### 11.4 CrewAI Role + Task

```python
# Role ≈ 带 Skill 的 Agent
researcher = Agent(
    role="Researcher",
    goal="Find relevant information",
    backstory="Expert at research...",
    tools=[search_tool, read_tool],
)
```

- Role 的 backstory/goal ≈ Skill 的元数据 + 指令
- Task ≈ Skill 的执行上下文

---

### 11.5 模式对比

| 框架 | Skill 等价物 | 粒度 | 特点 |
|------|------------|------|------|
| **Claude Code** | SKILL.md + 资源目录 | 最细 | 渐进式披露，文件系统即接口 |
| **LangChain** | Tool + Prompt Template | 中 | 函数级，LangGraph 编排 |
| **OpenAI** | Function + Instructions | 粗 | JSON Schema，System Prompt |
| **CrewAI** | Role + Backstory | 粗 | 角色扮演型，自然语言描述 |

---

## 十二、Python LLM 项目中的 Skill 实践建议

### 12.1 将 Skill 理念融入 RAG/Agent 项目

**项目中的 Skill 目录结构**：
```
project/
├── skills/
│   ├── document-qa/
│   │   ├── SKILL.md              # QA 流程指令
│   │   ├── prompts/              # Prompt 模板
│   │   │   ├── intent.jinja2
│   │   │   ├── rewrite.jinja2
│   │   │   └── generate.jinja2
│   │   ├── references/
│   │   │   ├── reranking.md      # 重排序策略
│   │   │   └── hybrid-search.md  # 混合检索配置
│   │   └── scripts/
│   │       ├── eval_ragas.py     # RAG 评估脚本
│   │       └── chunk_audit.py    # 切片质量审计
│   └── data-analysis/
│       ├── SKILL.md
│       └── scripts/
```

---

### 12.2 Skill 驱动的 Agent 编排

**示例**：
```python
# 用 Skill 理念组织 Agent 节点
class DocumentQASkill:
    """Skill: 文档问答流程"""
    
    def __init__(self, llm, vector_store, reranker):
        self.llm = llm
        self.vector_store = vector_store
        self.reranker = reranker
    
    def execute(self, query: str) -> SkillResult:
        # Step 1: 意图识别（Skill 指令驱动）
        intent = self._recognize_intent(query)
        
        # Step 2: 查询改写
        rewritten = self._rewrite_query(query, intent)
        
        # Step 3: 检索 + 重排序
        docs = self._retrieve_and_rerank(rewritten)
        
        # Step 4: 验证中间产物
        self._validate_docs(docs)
        
        # Step 5: 生成
        answer = self._generate(query, docs)
        
        return SkillResult(answer=answer, references=docs)
```

---

## 十三、必须测试的场景清单

- [ ] Skill 被正确发现（frontmatter 解析）
- [ ] Skill 被正确触发（description 匹配）
- [ ] Skill 指令被正确执行
- [ ] Skill 资源被正确加载（references/ / scripts/）
- [ ] Skill Token 开销符合预期（L1 ~100, L2 <5000）
- [ ] Skill 渐进式披露正常（不触发不加载正文）
- [ ] Skill 组合模式正常（Skill 调用 Skill）
- [ ] Skill + MCP Tool 集成正常
- [ ] Skill + Subagent 模式正常
- [ ] Skill 反馈循环正常（验证 → 修复 → 重复）
- [ ] Skill Gotchas 被正确理解

---

## 十四、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **Skill 设计** | ❌ Skill 无 description 或描述模糊；❌ SKILL.md 超过 500 行；❌ Knowledge-First 而非 Action-First |
| **渐进式披露** | ❌ L1 元数据超过 100 tokens；❌ L2 正文超过 5000 tokens；❌ 不触发就加载正文 |
| **触发机制** | ❌ description 太模糊（"Helps with PDFs"）；❌ 关键词匹配而非语义匹配 |
| **内容质量** | ❌ 堆 MUST 而不解释 Why；❌ 无 Gotchas 段落；❌ 示例不具体 |
| **资源管理** | ❌ 文件引用深度 > 1 层；❌ scripts/ 依赖包未列出；❌ references/ 有时效敏感信息 |
| **集成** | ❌ Skill 内部 Tool 调用无 timeout；❌ Skill 组合模式无最终仲裁者 |
| **测试** | ❌ 无评估场景；❌ 未在目标模型上测试；❌ 未收集团队反馈 |

---

## 十五、与其他角色的协作

- **与 [agent.md](agent.md) 的关系**：Skill 集成参考 agent.md §十六
- **与 [prompt-engineering.md](prompt-engineering.md) 的关系**：Skill 中的 Prompt 必须遵循 Prompt 工程规范
- **与 [mcp.md](mcp.md) 的关系**：Skill 可以编排多个 MCP Tool
- **与 [rag-evaluation.md](rag-evaluation.md) 的关系**：Skill 的评测参考 RAG 评测规范

---

**最后更新**：2026-06-01
**维护者**：AI Agent
