> **最后核对日期**：2026-06-01 | **核对方式**：Context7 查官方文档
> **AI 库版本基准**：MCP Python SDK 1.12.4+ / LangChain 1.0+ / LangGraph 1.0.8+
> **复核周期**：每季度（3/6/9/12 月）| **责任人**：维护者

# MCP (Model Context Protocol) 规范

> 适用场景：开发 MCP Server、设计 MCP Tool、MCP 与 Agent 架构集成。
>
> 本文件是 Python + FastAPI + Agent + RAG 项目的 **MCP 核心规范**，与 [agent.md](agent.md) 形成「网状约束」。

---

## 一、本质结论

**一句话结论**：MCP = AI 应用连接外部能力的统一协议标准（类比 USB-C）。

**核心类比**：
- MCP = USB-C（一个接口适配所有外部能力）
- MCP Server = USB 设备（提供具体功能）
- MCP Host = 电脑（管理多个设备）

**关键点**：
1. MCP 基于 JSON-RPC 的 Host-Client-Server 三层架构
2. 三大原语：Tool（模型控制）、Resource（应用控制）、Prompt（用户控制）
3. 当前最新版本：2025-11-25

---

## 二、核心架构：Host-Client-Server 三层模型

```
┌──────────────────────────────────────────────────┐
│              MCP Host (AI 应用)                    │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│   │ Client 1 │ │ Client 2 │ │ Client 3 │        │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘        │
└────────┼────────────┼────────────┼───────────────┘
         │            │            │
    ┌────▼────┐  ┌────▼────┐  ┌───▼─────┐
    │ Server A│  │ Server B│  │ Server C│
    │(本地进程)│  │(数据库)  │  │(远程API) │
    └─────────┘  └─────────┘  └─────────┘
```

### 三个核心角色

| 角色 | 职责 | 关键点 |
|------|------|--------|
| **Host** | 容器和协调者，创建管理多个 Client | 控制权限、安全策略、LLM 集成、上下文聚合 |
| **Client** | 与单个 Server 保持 1:1 有状态会话 | 协议协商、能力交换、消息路由、订阅管理 |
| **Server** | 暴露 Resources/Tools/Prompts 三大原语 | 独立运行、专注职责、可本地可远程 |

---

## 三、MCP 核心概念和术语

### 3.1 三大原语（Primitives）

#### Tool（工具）-- 模型控制

**本质**：Server 暴露的可执行函数，LLM 自主决定调用

**协议操作**：`tools/list`（发现） / `tools/call`（执行）

**inputSchema**：JSON Schema 定义输入参数（必须 `type: "object"`）

**outputSchema**：可选，定义结构化输出格式

**annotations**：行为元数据提示（readOnly / destructive / idempotent / openWorld）

**示例**：
```json
{
  "name": "get_weather",
  "title": "Weather Data Retriever",
  "description": "Get current weather data for a location",
  "inputSchema": {
    "type": "object",
    "properties": {
      "location": { "type": "string", "description": "City name or zip code" }
    },
    "required": ["location"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true
  }
}
```

---

#### Resource（资源）-- 应用控制

**本质**：Server 暴露的上下文数据，由应用层（非 LLM）决定何时注入

**协议操作**：`resources/list` / `resources/read` / `resources/templates/list`

**URI 标识**：每个资源用唯一 URI 标识（如 `file:///project/src/main.rs`）

**支持能力**：`subscribe`（资源变更订阅） + `listChanged`（列表变更通知）

**Resource Templates**：URI 模板支持参数化资源（`file:///{path}`）

---

#### Prompt（提示模板）-- 用户控制

**本质**：Server 暴露的结构化 Prompt 模板，由用户显式选择触发

**协议操作**：`prompts/list` / `prompts/get`

**用户交互**：通常通过 UI 命令（如斜杠命令）触发，支持参数化

---

### 3.2 客户端能力

| 能力 | 说明 |
|------|------|
| **Sampling** | Server 反向请求 Client 的 LLM 进行文本生成（`sampling/createMessage`） |
| **Elicitation** | Server 请求用户输入（确认、表单等） |
| **Roots** | Client 向 Server 暴露文件系统根目录列表 |

---

### 3.3 传输层（Transport）

| 传输方式 | 适用场景 | 说明 |
|----------|---------|------|
| **stdio** | 本地进程 | Client 启动 Server 子进程，通过 stdin/stdout 通信 |
| **Streamable HTTP** | 远程服务（推荐） | 单一 HTTP 端点，支持 POST + GET，可选 SSE 流式 |
| **SSE（旧版）** | 向后兼容 | 2024-11-05 版本遗留，已被 Streamable HTTP 取代 |

---

### 3.4 生命周期（Lifecycle）

三个阶段：

1. **Initialization** -- Client 发送 `initialize` 请求，协商协议版本和能力
2. **Operation** -- 正常的消息交换（tools/call, resources/read 等）
3. **Shutdown** -- 连接关闭

**示例**：
```json
// Client -> Server: initialize
{
  "jsonrpc": "2.0", "id": 1, "method": "initialize",
  "params": {
    "protocolVersion": "2025-11-25",
    "capabilities": { "sampling": {}, "elicitation": {} },
    "clientInfo": { "name": "my-client", "version": "1.0.0" }
  }
}

// Server -> Client: 响应
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "protocolVersion": "2025-11-25",
    "capabilities": { "tools": { "listChanged": true }, "resources": {} },
    "serverInfo": { "name": "my-server", "version": "1.0.0" }
  }
}
```

---

## 四、MCP Server 开发规范（Python FastMCP）

### 4.1 Python FastMCP 开发模式

```python
from mcp.server.fastmcp import FastMCP

# 初始化 Server
mcp = FastMCP("my-server")

@mcp.tool()
async def search_docs(query: str, limit: int = 10) -> dict:
    """
    Search documents by keyword.
    
    Args:
        query: Search keyword
        limit: Max results to return
    """
    # 业务逻辑
    results = await do_search(query, limit)
    return {"results": results, "total": len(results)}

@mcp.resource("db://schema/{table_name}")
async def get_table_schema(table_name: str) -> str:
    """Get database table schema."""
    schema = await fetch_schema(table_name)
    return schema

@mcp.prompt()
def code_review(code: str, language: str = "python") -> str:
    """Generate a code review prompt."""
    return f"Please review this {language} code:\n\n```{language}\n{code}\n```"

# 启动
if __name__ == "__main__":
    mcp.run(transport="stdio")         # 本地模式
    # mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)  # 远程模式
```

---

### 4.2 Transport 选型决策

```
需要远程访问？
  ├── 是 → Streamable HTTP（支持 SSE 流式 + 多客户端）
  │        FastMCP(host="0.0.0.0", port=8000)
  │        mcp.run(transport="streamable-http")
  │
  └── 否 → stdio（本地集成，零网络开销）
           mcp.run(transport="stdio")
```

---

### 4.3 日志规范（强制）

stdio 模式下 stdout 用于协议通信，**禁止** `print()` 输出日志：

```python
import sys
import logging

# ❌ 错误：print 会破坏 stdio 协议
print("Processing request")

# ✅ 正确：输出到 stderr
print("Processing request", file=sys.stderr)

# ✅ 正确：使用 logging
logging.info("Processing request")
```

---

## 五、MCP Tool 设计原则

### 5.1 命名规范

**强制**：
- **snake_case** 命名，动词开头
- 简洁但有语义：`search_documents` / `get_weather` / `create_user`

**❌ 禁止**：
- `tool1`、`func`、`doStuff`（太模糊）

---

### 5.2 描述规范（核心 -- 直接影响 LLM 选择准确率）

**强制**：
- **description 必须写**，且要像写给人看的 API 文档
- 说明"这个工具做什么"、"什么场景用"、"返回什么"
- 每个参数的 `description` 必须写清楚含义、格式、约束

**✅ 正确示例**：
```python
@mcp.tool()
async def query_database(sql: str, database: str = "default") -> dict:
    """
    Execute a read-only SQL query against the specified database.
    Use this tool when you need to retrieve structured data from the database.
    Only SELECT queries are allowed; DML/DDL statements will be rejected.
    
    Args:
        sql: The SQL SELECT query to execute. Must start with SELECT.
        database: Target database name. Defaults to 'default'.
    """
```

**❌ 错误示例**：
```python
@mcp.tool()
async def query(sql: str) -> str:
    """Query."""
```

---

### 5.3 ToolAnnotations 使用规范

**强制**：所有 Tool 必须声明 annotations

**示例**：
```python
# 只读查询工具
annotations = {
    "readOnlyHint": True,       # 不修改环境
    "destructiveHint": False,   # 非破坏性
    "idempotentHint": True,     # 幂等
    "openWorldHint": False      # 封闭世界（不访问外部网络）
}

# 写入操作工具
annotations = {
    "readOnlyHint": False,      # 修改环境
    "destructiveHint": True,    # 可能破坏性更新
    "idempotentHint": False,    # 非幂等
    "openWorldHint": True       # 开放世界（可能调用外部 API）
}
```

**Annotations 说明**：

| 标注 | 默认值 | 含义 |
|------|--------|------|
| `readOnlyHint` | false | true = 不修改任何环境状态 |
| `destructiveHint` | true | false = 仅增量更新，不做破坏性操作 |
| `idempotentHint` | - | true = 相同参数重复调用结果一致 |
| `openWorldHint` | - | true = 访问外部世界（网络、文件系统） |

---

### 5.4 错误处理

两层错误机制：

```python
# 层 1：协议错误（JSON-RPC 标准）
# 场景：未知工具、服务器内部错误
# 直接返回 JSON-RPC error response

# 层 2：工具执行错误（isError: true）
# 场景：输入校验失败、业务逻辑错误、API 调用失败
@mcp.tool()
async def transfer_money(to: str, amount: float) -> dict:
    """Transfer money to an account."""
    if amount <= 0:
        return {
            "content": [{"type": "text", "text": "Amount must be positive"}],
            "isError": True  # 标记为执行错误，不是协议错误
        }
    # 正常逻辑...
    return {"content": [{"type": "text", "text": f"Transferred {amount} to {to}"}]}
```

---

### 5.5 结构化输出（outputSchema）

当工具返回结构化数据时，使用 `outputSchema` + `structuredContent`：

```python
# 定义 outputSchema
{
    "name": "get_weather_data",
    "outputSchema": {
        "type": "object",
        "properties": {
            "temperature": { "type": "number" },
            "conditions": { "type": "string" },
            "humidity": { "type": "number" }
        },
        "required": ["temperature", "conditions", "humidity"]
    }
}

# 返回时同时包含非结构化 + 结构化
{
    "content": [{"type": "text", "text": "22.5C, partly cloudy, 65% humidity"}],
    "structuredContent": {
        "temperature": 22.5,
        "conditions": "Partly cloudy",
        "humidity": 65
    }
}
```

---

### 5.6 分页规范（强制）

列表类操作**必须**支持 cursor 分页：

```python
# ❌ 错误：一次性返回所有数据
@mcp.tool()
async def list_items() -> dict:
    return {"items": fetch_all_10000_items()}

# ✅ 正确：支持分页
@mcp.tool()
async def list_items(cursor: str = None, limit: int = 50) -> dict:
    """List items with pagination. Use cursor for next page."""
    items, next_cursor = fetch_page(cursor, limit)
    return {"items": items, "nextCursor": next_cursor}
```

---

## 六、MCP 与 Agent 架构集成模式

### 6.1 集成本质

MCP 在 Agent 架构中的定位是**工具层标准化**：

```
Agent (LangGraph / smolagents / 自研)
   │
   ├── 传统方式：每个工具硬编码集成（N 个工具 = N 种适配）
   │
   └── MCP 方式：统一协议接入（N 个工具 = 1 种适配）
         │
         ├── MCP Server A（文档检索）
         ├── MCP Server B（数据库查询）
         ├── MCP Server C（代码执行）
         └── MCP Server D（外部 API）
```

---

### 6.2 LangGraph 集成模式（推荐使用官方 adapter）

> **必须使用官方 `langchain-mcp-adapters` 包**，**禁止**手写 StructuredTool 转换（易出错且难维护）。
> 安装：`uv add langchain-mcp-adapters`

```python
# ✅ 推荐：使用官方 MultiServerMCPClient（LangGraph 1.0+）
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

# 第一步：配置多个 MCP Server
server_configs = {
    "document": {
        "command": "python",
        "args": ["-m", "my_document_mcp_server"],
        "transport": "stdio",
    },
    "database": {
        "url": "http://localhost:8001/mcp",  # 远程 Streamable HTTP
        "transport": "streamable_http",
    },
}

# 第二步：连接并自动转换为 LangChain Tool
async with MultiServerMCPClient(server_configs) as client:
    tools = client.get_tools()  # 自动转换，无需手动包装
    agent = create_react_agent(model, tools)
    result = await agent.ainvoke({"messages": [("user", "查询最近文档")]})
```

❌ **禁止**：手写 StructuredTool 包装（如以下旧写法）：
```python
# ❌ 旧写法（易出错，已在 langchain-mcp-adapters 中封装）
from langchain_core.tools import StructuredTool
lc_tool = StructuredTool(
    name=tool.name,
    description=tool.description,
    args_schema=tool.inputSchema,
    coroutine=lambda args, s=session, n=tool.name: s.call_tool(n, args),
)
```

---

### 6.3 与现有 RAG 架构的集成点

```
用户查询
   │
   ▼
意图识别（LangGraph Node）
   │
   ├── 通用对话 → 直接 LLM
   │
   └── 知识检索 → MCP Tool 调用
         │
         ├── search_documents(query)    ← MCP Server: 文档检索
         ├── query_database(sql)        ← MCP Server: 结构化查询
         ├── get_knowledge_graph(entity)← MCP Server: 图数据库
         │
         ▼
      Reranker + 聚合
         │
         ▼
      LLM 流式生成（SSE）
```

---

### 6.4 Sampling 反向调用模式

MCP 独特能力：Server 可以**反向请求** Client 的 LLM：

```json
// Server -> Client: 请求 LLM 生成
{
  "method": "sampling/createMessage",
  "params": {
    "messages": [{"role": "user", "content": {"type": "text", "text": "Summarize this..."}}],
    "modelPreferences": { "hints": [{"name": "deepseek-chat"}] },
    "systemPrompt": "You are a helpful assistant.",
    "maxTokens": 500,
    "includeContext": "thisServer"
  }
}
```

**适用场景**：Server 需要 LLM 辅助处理（如代码审查 Server 需要 LLM 分析代码质量）

---

## 七、常见陷阱和最佳实践

### 陷阱 1：Tool description 写得太烂

**❌ 错误**：
```python
@mcp.tool()
async def query(sql: str) -> str:
    """Query."""
```

**✅ 正确**：
```python
@mcp.tool()
async def query_database(sql: str) -> dict:
    """
    Execute a read-only SQL query. Use when you need structured data retrieval.
    Only SELECT statements allowed. Returns JSON array of rows.
    Args:
        sql: SELECT query string. Must not contain DML/DDL.
    """
```

---

### 陷阱 2：stdio 模式下用 print 输出

**❌ 错误**：
```python
print("debug info")  # stdout 被协议占用，print 会破坏通信
```

**✅ 正确**：
```python
logging.info("debug info")
print("debug info", file=sys.stderr)
```

---

### 陷阱 3：Tool 返回值格式不对

**❌ 错误**：
```python
@mcp.tool()
async def get_info() -> str:
    return "some data"
```

**✅ 正确**：
```python
@mcp.tool()
async def get_info() -> dict:
    return {"content": [{"type": "text", "text": "some data"}]}
```

---

### 陷阱 4：Tool 粒度设计不当

**❌ 错误（太粗）**：
```python
@mcp.tool()
async def do_everything(action: str, params: dict) -> dict:
    """Do everything with the database."""
```

**❌ 错误（太细）**：
```python
@mcp.tool()
async def get_user_name(user_id: int) -> str: ...
@mcp.tool()
async def get_user_email(user_id: int) -> str: ...
@mcp.tool()
async def get_user_age(user_id: int) -> int: ...
```

**✅ 正确**：
```python
@mcp.tool()
async def get_user(user_id: int) -> dict:
    """Get user profile by ID. Returns name, email, age, etc."""
    ...
```

---

### 陷阱 5：忽视安全

**强制**：
- Tool 实现必须**验证和消毒所有输入**
- 资源访问必须**鉴权**
- 远程 Server 必须配置 **OAuth / Token 验证**
- **禁止**在 Tool 中暴露系统内部信息

---

### 陷阱 6：不做分页

**❌ 错误**：
```python
@mcp.tool()
async def list_items() -> dict:
    return {"items": fetch_all_10000_items()}
```

**✅ 正确**：
```python
@mcp.tool()
async def list_items(cursor: str = None, limit: int = 50) -> dict:
    """List items with pagination. Use cursor for next page."""
    items, next_cursor = fetch_page(cursor, limit)
    return {"items": items, "nextCursor": next_cursor}
```

---

## 八、协议版本与生态演进

| 版本 | 日期 | 关键变化 |
|------|------|---------|
| 2024-11-05 | 2024.11 | 初始版本，HTTP+SSE 传输 |
| 2025-03-26 | 2025.03 | Streamable HTTP 取代 HTTP+SSE |
| 2025-06-18 | 2025.06 | Elicitation、Sampling 增强 |
| **2025-11-25** | **2025.11** | **当前最新版**：Tool annotations、outputSchema、Task 增强、订阅机制重构 |

### 关键生态组件

| 组件 | 说明 |
|------|------|
| `mcp` Python SDK | 官方 Python SDK，含 FastMCP 快速开发框架 |
| `@modelcontextprotocol/sdk` | 官方 TypeScript SDK |
| MCP Server Registry | 官方 Server 注册中心（modelcontextprotocol.io/registry） |
| MCP Inspector | 调试工具，可视化测试 MCP Server |
| Claude Desktop / Claude Code | 原生支持 MCP 的 Host 应用 |

---

## 九、必须测试的场景清单

- [ ] Tool 被正确发现（`tools/list`）
- [ ] Tool 被正确调用（`tools/call`）
- [ ] Tool 描述被 LLM 正确理解（选择准确率）
- [ ] Tool 输入校验（必填参数、类型校验）
- [ ] Tool 输出格式（content / structuredContent）
- [ ] Tool 错误处理（isError: true）
- [ ] ToolAnnotations 正确声明
- [ ] 分页功能正常（cursor 传递）
- [ ] stdio 模式日志不破坏协议
- [ ] 远程 Server 鉴权正常
- [ ] Resource 订阅和通知正常
- [ ] Prompt 模板被正确触发

---

## 十、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **Tool 设计** | ❌ Tool 无 description 或描述模糊；❌ Tool 无 inputSchema；❌ ToolAnnotations 不声明 |
| **Tool 粒度** | ❌ 一个 Tool 包办所有事（太粗）；❌ 拆得太细（太多 Tool，LLM 选择困难） |
| **日志** | ❌ stdio 模式 print stdout（破坏协议）；❌ 日志中暴露敏感信息 |
| **错误处理** | ❌ 业务错误不返回 isError: true；❌ 协议错误和业务错误混淆 |
| **安全** | ❌ Tool 无输入校验消毒；❌ 远程 Server 无鉴权；❌ Tool 暴露系统内部信息 |
| **分页** | ❌ 列表操作不分页（一次性返回所有数据）；❌ 分页无 cursor 支持 |
| **超时** | ❌ Tool 无 timeout；❌ Tool 无 retry 机制 |
| **输出** | ❌ Tool 返回值格式不对（直接返回字符串而非 content）；❌ 结构化数据不使用 outputSchema |

---

## 十一、与其他角色的协作

- **与 [agent.md](agent.md) 的关系**：MCP Tool 集成参考 agent.md §十五
- **与 [prompt-engineering.md](prompt-engineering.md) 的关系**：MCP Prompt 原语必须遵循 Prompt 工程规范
- **与 [skill.md](skill.md) 的关系**：Skill 可以编排多个 MCP Tool
- **与 [rag-evaluation.md](rag-evaluation.md) 的关系**：MCP Tool 的评测参考 RAG 评测规范

---

**最后更新**：2026-06-01
**维护者**：AI Agent
