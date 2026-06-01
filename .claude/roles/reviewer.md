# Reviewer 规范（代码审查 + LLM 应用专项）

> 适用场景：Python + FastAPI + Agent + RAG 项目的 PR Review / 代码审查。
>
> 与 [backend-fastapi.md](backend-fastapi.md) / [frontend.md](frontend.md) / [dba.md](dba.md) / [devops.md](devops.md) / [agent.md](agent.md) 协同。

---

## 一、审查清单

### 1. 设计与架构

- [ ] 是否符合 [backend-fastapi.md](backend-fastapi.md) 分层规范（API → Service → Repository）？
- [ ] 是否避免循环依赖？
- [ ] 是否有清晰的模块边界（按业务域拆分）？
- [ ] 是否复用现有工具类 / 公共方法（不重复造轮子）？
- [ ] 重复代码是否已提取为工具函数或公共方法（同一逻辑 ≥ 2 次必须提取）？
- [ ] 外部服务调用是否通过 Client 类封装（禁止 Service 层直接调用第三方 SDK）？
- [ ] 设计模式使用是否合理（禁止过度设计，禁止为不存在的需求预留模式）？
- [ ] 是否过度设计（为不存在的需求预留接口）？
- [ ] **架构决策**是否与 [CLAUDE.md](../../CLAUDE.md) 项目结构一致？

### 2. 功能与正确性

- [ ] 业务逻辑是否正确（边界条件、空值、异常路径）？
- [ ] 并发场景是否安全（race condition、deadlock）？
- [ ] 事务边界是否合理（**单请求单事务**，事务内无 IO）？
- [ ] 是否有充分的输入校验（Pydantic Schema）？
- [ ] 错误处理是否完整（每个异常路径都有处理）？
- [ ] 是否处理了外部依赖失败（LLM timeout、DB connection lost）？

### 3. 可读性与可维护性

- [ ] 函数 / 类 / 变量命名是否清晰（见名知意）？
- [ ] 函数长度是否合理（**单函数 < 50 行**，超大函数拆解）？
- [ ] 是否有必要的注释（解释**为什么**，而非**是什么**）？
- [ ] 类型注解是否完整（参数、返回值）？
- [ ] 复杂逻辑是否有文档字符串？
- [ ] **魔法数字 / 字符串**是否抽到常量？
- [ ] 文件长度是否合理（**单文件 < 800 行**）？

### 4. 安全

- [ ] 是否有 SQL 注入风险（用 SQLAlchemy 参数化）？
- [ ] 是否有 XSS 风险（前端 `v-html` LLM 输出 / `html: true`）？
- [ ] 是否有 CSRF 风险（POST/PUT/DELETE 是否验证 origin）？
- [ ] 密码是否 bcrypt/argon2 哈希（**禁止**明文 / MD5 / SHA1）？
- [ ] 敏感信息（API Key / JWT Secret）是否走环境变量？
- [ ] 是否有越权风险（用户 A 可访问用户 B 数据）？
- [ ] 是否有 SSRF 风险（用户可控 URL 调外部 API）？
- [ ] **LLM 输入**是否做 Prompt 注入防护？
- [ ] **LLM 输出**是否做内容过滤（有害 / PII）？

### 5. 性能

- [ ] 是否有 N+1 查询（用 `selectinload` / `joinedload`）？
- [ ] 是否有不必要的全表扫描（缺索引）？
- [ ] 是否有大循环里的同步 IO（**必须** async）？
- [ ] 是否有不必要的内存拷贝（用 `shallowRef` / 生成器）？
- [ ] 前端是否有不必要的重渲染（用 `v-memo` / `computed`）？
- [ ] 是否有可缓存的热点数据（Redis / LRU）？
- [ ] **LLM 调用**是否启用语义缓存？
- [ ] **RAG 检索**是否限制 top_k（避免 token 爆炸）？

### 6. 异常处理与日志

- [ ] 是否吞掉异常（`except: pass`，**禁止**）？
- [ ] 异常信息是否带上下文（trace_id / user_id / request_id）？
- [ ] 日志是否结构化（JSON / 关键字段）？
- [ ] 日志是否输出敏感信息（密码 / API Key / PII）？
- [ ] 关键操作是否打 INFO 级别日志？
- [ ] 异常是否上报监控系统（Sentry / Langfuse）？

### 7. 测试

- [ ] 是否有单元测试（覆盖核心业务逻辑）？
- [ ] 是否有集成测试（API / 数据库）？
- [ ] 测试是否独立（不依赖外部服务，用 mock / testcontainers）？
- [ ] 测试数据是否真实（factory-boy / faker）？
- [ ] 覆盖率是否达标（**核心模块 ≥ 80%**，整体 ≥ 60%）？
- [ ] 是否有边界条件测试（空值、极端输入、并发）？
- [ ] **LLM 应用**是否有 offline eval（faithfulness / cost）？
- [ ] PR 是否破坏现有测试？

### 8. 前端专项

- [ ] Composition API + `<script setup>`（**禁止** Options API）？
- [ ] TypeScript 严格模式（`strict: true`）？
- [ ] 组件是否 < 500 行？
- [ ] 路由懒加载（`() => import(...)`）？
- [ ] SSE 连接是否正确取消（AbortController）？
- [ ] 流式消息是否节流（30ms）？
- [ ] LLM 输出是否过 DOMPurify？
- [ ] 用户输入是否做 XSS 防护？
- [ ] API Key / JWT 是否安全存储（httpOnly cookie）？

### 9. 后端专项

- [ ] **async def** 路由中无同步阻塞 IO？
- [ ] Pydantic v2 风格（`Mapped[T]` / `ConfigDict`）？
- [ ] 依赖注入用 FastAPI Depends（**禁止**手动 new）？
- [ ] 统一响应体 `R[T]`？
- [ ] 业务异常继承 `BizException`？
- [ ] 数据库连接池配置（pool_size ≥ 20）？
- [ ] 数据库迁移是否可回滚（`downgrade()` 已实现）？
- [ ] 配置走 Pydantic Settings（**禁止**硬编码）？
- [ ] 日志用 loguru（**禁止** print）？

### 10. 风格与一致性

- [ ] 是否通过 `ruff check` / `ruff format --check`？
- [ ] 是否通过 `mypy --strict`？
- [ ] 命名风格是否一致（snake_case 函数 / PascalCase 类）？
- [ ] import 顺序是否规范（标准库 → 第三方 → 本地）？
- [ ] 与项目其他文件风格是否一致？

### 11. 测试与构建

- [ ] CI 是否通过（lint / test / type-check）？
- [ ] 新依赖是否合理（不引入无用包）？
- [ ] Dockerfile 是否多阶段构建（构建 → 运行时）？
- [ ] 镜像是否锁定版本（**禁止** `latest`）？
- [ ] 数据库迁移是否与代码同步发布？
- [ ] 是否有破坏性变更（删字段 / 改接口签名）？如有，是否在 PR 描述中说明？

### 12. 🆕 LLM 应用专项（新增）

- [ ] **Prompt 版本化**：变更是否走 Prompt Registry（**禁止**硬编码）？
- [ ] **Prompt 评估**：变更是否跑 offline eval（**禁止**裸改 Prompt 上线）？
- [ ] **max_tokens 上限**：所有 LLM 调用是否设置（防成本失控）？
- [ ] **timeout / retry**：LLM 调用是否有超时和重试？
- [ ] **JSON 容错**：LLM 输出的 JSON 是否过 `JsonUtil.fixJson()` 7 步修复？
- [ ] **trace 完整**：每一跳 LLM 调用是否打 Langfuse trace（含 prompt/response/token）？
- [ ] **Embedding 一致性**：Embedding 模型版本是否固定，维度是否与向量库一致？
- [ ] **父子分段**：是否保留 `parent_chunk_id` / `brother_chunk_id`？
- [ ] **RAG 引用溯源**：返回 chunk 是否带 `source` / `score` / `metadata`？
- [ ] **Agent Loop 兜底**：ReAct / Plan-Execute 是否有 `max_iterations` 限制？
- [ ] **Tool 调用**：是否有 timeout / retry / 降级（无 fallback 直接抛异常视为不合格）？
- [ ] **Memory TTL**：短期 memory 是否有 TTL（防上下文无限膨胀）？
- [ ] **权限过滤**：向量检索是否在向量库层做 metadata filter（**禁止**应用层过滤）？
- [ ] **多租户**：是否携带 `tenant_id` / `accessible_by` 过滤（防越权）？
- [ ] **成本监控**：是否有 token 计数 + 成本告警？
- [ ] **可重现性**：生产 `temperature ≤ 0.7`（无 eval 验证不允许更高）？
- [ ] **敏感信息**：Prompt / 日志是否包含用户 PII（邮箱 / 手机 / 身份证）？
- [ ] **降级策略**：模型失败 / 检索失败是否有降级链（**禁止**所有降级都失败仍 500）？
- [ ] **缓存策略**：相同 query + context 是否走语义缓存？
- [ ] **Embedding 升级**：版本变更是否触发全量重建索引任务？
- [ ] **🔥 国产模型强制**：PR 中是否调用了国外 API（OpenAI / Anthropic / Cohere / Jina）？是否引入了 `openai` / `anthropic` SDK 作为生产依赖？主力模型是否为 DeepSeek？**违反视为 `[严重]` 阻断合并**

---

## 二、审查输出格式

```markdown
## PR Review

**总体评价**：[✅ LGTM / ⚠️ 需修改后合并 / ❌ 需重大重构]

### 严重程度说明

- `[严重]`：必须修复才能合并（影响功能 / 安全 / 性能 / 正确性）
- `[建议]`：建议修复（影响可维护性 / 风格）
- `[Nit]`：可选（拼写 / 注释 / 细节）

### 必改项（[严重]）

#### 1. [严重] 文件名:行号
**问题**：...
**影响**：...（性能 / 安全 / 正确性）
**建议**：...
**参考**：[backend-fastapi.md §分层规范](backend-fastapi.md#分层规范api--service--repository) / [agent.md §避坑清单](agent.md#二避坑清单llm-专属20-条)

```python
# ❌ 当前代码
def get_user_orders(user_id):
    ...

# ✅ 建议修改
async def get_user_orders(user_id: int) -> list[Order]:
    ...
```

### 建议项（[建议]）
...

### Nit（[Nit]）
...

### 亮点
- xxx 设计合理
- yyy 实现优雅

### 审查清单完成度
- [x] 设计与架构
- [x] 安全
- [ ] 测试（覆盖率不足）
- [x] LLM 专项
```

### 评级标准

| 评级 | 标准 | 处理 |
|------|------|------|
| **LGTM** | 0 个 `[严重]`，≤ 3 个 `[建议]` | 直接合并 |
| **需修改** | 0 个 `[严重]`，> 3 个 `[建议]` | 修改后合并 |
| **重大重构** | ≥ 1 个 `[严重]` | 修改后重新审查 |

---

## 三、审查原则（来自 Google eng-practices）

1. **快速审查**：PR 提交后 **24 小时内首响应**，避免阻塞提交者
2. **小批量**：单次审查 PR **< 400 行**（不含 lockfile / 自动生成）
3. **对事不对人**：聚焦代码本身，避免人身攻击
4. **解释为什么**：提建议时说明原因（参考哪条规范 / 哪个反例）
5. **区分必须与可选**：用 `[严重]` / `[建议]` / `[Nit]` 标注
6. **承认自己的错误**：被作者说服时大方承认
7. **避免完美主义**：不阻塞 PR 等"小改进"，开 issue 跟踪
8. **保护作者尊严**：赞美亮点，不只挑刺

---

## 四、审查流程建议

| 阶段 | 动作 | 时间 |
|------|------|------|
| **1. 整体把握** | 看 PR 描述、变更范围、关联 issue | 2 min |
| **2. 设计审查** | 看架构 / 分层 / 复用 | 5 min |
| **3. 细节审查** | 逐文件读代码，对照清单 | 15-30 min |
| **4. 测试审查** | 检查覆盖率、边界、eval | 5 min |
| **5. CI 检查** | 看 CI 日志（lint/test/build） | 2 min |
| **6. 输出反馈** | 按格式输出 review | 5 min |
| **总计** | — | **< 1h** |

### 工具辅助

| 工具 | 用法 |
|------|------|
| **Ruff** | `uv run ruff check .` 自动检查 PEP8 / 风格 |
| **Mypy** | `uv run mypy app/` 类型检查 |
| **Pytest** | `uv run pytest --cov` 覆盖率 |
| **RAGAS** | `uv run pytest tests/eval/` 评估 RAG 质量 |
| **Langfuse** | 查 trace 完整度 / 成本 / 延迟 |
| **pip-audit** | `uv run pip-audit` 依赖漏洞扫描 |
| **Bandit** | `uv run bandit -r app/` 安全扫描 |

---

## 五、必须测试的场景清单

- [ ] 业务正常路径
- [ ] 业务异常路径（错误输入 / 外部依赖失败）
- [ ] 边界值（空字符串 / 0 / 最大值 / None）
- [ ] 并发场景（race condition / 死锁）
- [ ] 权限校验（未登录 / 越权 / 角色不足）
- [ ] 限流触发
- [ ] 性能（大数据量 / 高并发）
- [ ] 兼容性（Python 版本 / 依赖版本）
- [ ] **LLM 输出解析失败**（7 步修复管道）
- [ ] **RAG 召回率 / 准确率**
- [ ] **Agent Loop 兜底**（max_iterations 触发）
- [ ] **Embedding 升级兼容性**
- [ ] **向量库权限过滤**（跨租户 / 越权）

---

## 六、禁止事项（完整清单）

| 类别 | 禁止 |
|------|------|
| **审查态度** | ❌ 人身攻击；❌ 完美主义阻塞 PR；❌ 不解释原因就拒绝 |
| **审查范围** | ❌ 单次审查 > 400 行；❌ 不看 PR 描述就开审；❌ 跳过 CI 检查 |
| **输出** | ❌ 只说"不行"不说"为什么"；❌ 混用严重/建议等级；❌ 复述代码而非指出问题 |
| **测试** | ❌ PR 无测试就合并；❌ 测试覆盖率下降不阻断；❌ 测试调真实 LLM |
| **LLM** | ❌ Prompt 改动不跑 eval；❌ max_tokens 不设；❌ 无 trace；❌ 父子分段丢失；❌ Embedding 升级不重建索引；❌ **调用 OpenAI / Anthropic / Cohere / Jina 等国外 API**；❌ **引入 `openai` / `anthropic` SDK 作为生产依赖**；❌ **降级链兜底不是国产模型** |
| **安全** | ❌ 密码明文；❌ API Key 提交；❌ LLM 输出不过滤；❌ 跨租户数据串 |
| **流程** | ❌ 24h 不响应；❌ 不在 PR 描述中说破坏性变更；❌ 数据库迁移与代码不同步 |
