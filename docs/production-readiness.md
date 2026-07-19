# WorkMind 生产就绪清单

> 审查基线：2026-07-16。本文记录当前代码事实与上线门禁，不是上线承诺。  
> 分轨排期与会签清单见：[production-acceptance-schedule.md](production-acceptance-schedule.md)。

## 结论

当前判定仍为 **NO-GO**（多 worker / live RAG / 生产数据副本等外部门禁未关）。  
**2026-07-17 代码审计批次**已关闭一批可本地修复缺陷（审计清单已随修复完成归档移除，明细见 git 历史）：知识库读路径隔离、Agent/ERP/Workflow SSE 终态、前端 stateVersion / detach、Selenium S-01~S-10 本地通过（193 后端 + 18 前端单测）。

状态仅使用以下四类：

| 状态 | 含义 |
|---|---|
| `已修复` | 已实现，并在当前工作树完成与风险相称的自动化或人工复验；不包含外部环境验收 |
| `本轮处理` | 已进入当前修复批次，但尚未完成全部复验，不视为关闭 |
| `上线前外部验收` | 需要真实依赖、生产拓扑、业务负责人或专门压测环境验证 |
| `明确产品边界` | 当前有意不提供该生产能力，必须在 UI、文档和销售口径中明确 |

`已修复` 只代表代码和本地回归已闭环，不替代下文列出的外部验收。任何 P0 外部门禁未取得证据时，整体结论仍是 **NO-GO**。

## 本轮修复摘要

- Auth/数据隔离：access 与 refresh 均回查当前账号状态和角色；缓存、会话、报告、审批、知识库文档按用户隔离；开发免认证模式也使用真实数据库用户 ID。
- 流式与长任务：统一处理 SSE done/error/EOF/abort；ERP 与 Workflow 受理后不再因浏览器断线被隐式取消，状态可查询，显式取消写入持久终态。
- Workflow 生命周期：配置停用只阻止新任务；已受理任务即使模板不再出现在活动列表中，也能用只读运行元数据恢复并完成、失败或取消，所有终态安全返回可选模板页。
- 数据与 RAG：文档和切片同事务写删，数据库成为文档清单权威来源；BM25 按分类和数据库版本刷新；迁移兼容非 UUID 文档、孤儿切片与重复切片，不再静默丢数据。
- 业务契约：ERP 服务端重算金额/天数并提供 owner、幂等和 fail-closed；Agent 配置真实控制模型、工具和步数，未接入通知不再伪装为可用；Prompt/Config 增加校验和乐观版本控制。
- 监控与交付：预算使用 Redis 原子预留/结算，统计使用 PostgreSQL 聚合和统一定价；数据库时间统一存 UTC-naive，预算日界线、账本 TTL、监控分组与展示统一使用可配置业务时区；补齐前端容器、Nginx SSE 代理、readiness、CI 服务依赖和生产文档；登录页完成真实浏览器 smoke。

### 2026-07-20 批次运维注意事项

- **认证对 Redis fail-closed**：refresh token 采用一次性 jti 轮换/吊销，凭据登记在 Redis；Redis 不可用时登录与刷新返回 503（宁拒绝、不降级签发不可轮换的 token）。Redis 可用性告警必须覆盖认证链路。
- **容器切换非 root 的升级步骤**：后端镜像改为 uid 10001（appuser）运行。全新部署卷属主自动正确；**旧部署已存在的 `wm_uploads`/`wm_hf_cache` 卷可能为 root 属主**，升级前需一次性 `chown -R 10001:10001`（可用临时 root 容器执行），否则上传与 HF 模型缓存写入失败。
- **torch 2.6.0+cpu 锁文件为手动最小更新**（修复 CVE-2025-32434）：上线前必须在 Linux/CI 用 `scripts/regenerate_linux_cpu_lock.sh` 重新解析全部传递依赖并通过 `uv pip check`。

## P0：上线阻断

| ID | 问题与影响 | 主要位置 | 状态 | 关闭条件 |
|---|---|---|---|---|
| P0-01 | Chat 缓存键未按用户/会话完整隔离，可能串用上下文 | `server-py/app/services/cache.py`、`server-py/app/routes/chat.py` | 已修复 | 用户、会话、system prompt、历史、角色和模型均进入缓存上下文，并有隔离回归测试 |
| P0-02 | Refresh/access token 信任旧角色或账号状态；删除、停用或降权不能及时生效 | `server-py/app/routes/auth.py`、`server-py/app/auth/` | 已修复 | 所有受保护请求和 refresh 回查当前用户、角色与 `is_active`；失败时 fail-closed |
| P0-03 | 会话 ID、知识库上传认证、退出后的业务状态/SSE 清理不完整，存在越权或脏状态风险 | `server-py/app/routes/knowledge.py`、`frontend/src/stores/auth.js`、各业务 store | 已修复 | session owner 校验、上传认证、logout 取消流并清空业务 store 均有本地回归 |
| P0-04 | Workflow 运行态和 checkpoint 依赖进程内内存，resume 缺 owner/CAS；重复点击可能重复执行 | `server-py/app/routes/workflow.py`、`server-py/app/services/workflow/`、`frontend/src/stores/workflow.js` | 上线前外部验收 | 代码已改为 Redis 快照/锁、owner 与显式终态；仍需真实 Redis、多 worker、重启与并发验收 |
| P0-05 | ERP 申请缺可靠 owner、幂等和 fail-closed 校验，可能越权、重复落库或错误成功 | `server-py/app/routes/erp.py`、`server-py/app/services/erp/`、`server-py/app/models/entities.py` | 上线前外部验收 | 代码已服务端重算、owner 隔离、幂等单记录和异常回滚；仍需真实 PG 并发故障注入 |
| P0-06 | 客户端断开 SSE 会取消已受理的 ERP/Workflow 任务，造成业务状态不确定 | `server-py/app/utils/sse_disconnect.py`、ERP/Workflow SSE 路由 | 上线前外部验收 | 代码已将断线与业务取消分离并提供状态查询/显式取消；仍需进程重启和长连接故障演练 |
| P0-07 | 登录页依赖的 Element Plus 组件/CSS 注册缺失且根布局未撑满视口 | `frontend/src/main.js`、`frontend/src/plugins/icons.js`、`frontend/src/App.vue` | 已修复 | 生产构建通过；浏览器验证全屏登录、未登录重定向、空表单校验且控制台无告警 |

## P1：高优先级生产缺口

| ID | 问题与影响 | 主要位置 | 状态 | 关闭条件 |
|---|---|---|---|---|
| P1-01 | 多模块 SSE 存在 401 重入、EOF 无终态、done 契约错位、切页/切会话不取消等生命周期问题 | `frontend/src/utils/http.js`、各业务 store、后端 SSE 路由 | 已修复 | 统一解析器和 store 生命周期覆盖 done/error/EOF/abort；前端契约测试通过 |
| P1-02 | Agent 工具、报告或持久化失败时可能仍输出 done/成功 | `server-py/app/routes/agent.py`、`server-py/app/services/agent/` | 已修复 | 关键阶段失败只输出结构化 error；报告按 owner 隔离；未接入工具不允许绑定 |
| P1-03 | Knowledge 的 sessionId、score、清空会话和前后端字段契约不一致 | `frontend/src/stores/knowledge.js`、`server-py/app/routes/knowledge.py` | 已修复 | 上传、查询、来源、历史、清空和删除权限契约已闭环并有测试 |
| P1-04 | 文档元信息与向量切片分两次事务写删，失败可留下孤儿数据；BM25 为进程内全局状态 | `server-py/app/services/rag/ingest.py`、`pgvector_store.py`、`hybrid_retriever.py` | 上线前外部验收 | 真实 PG 故障注入证明原子/可补偿；多 worker 检索一致；大数据索引计划验证 |
| P1-05 | Config CRUD 与 Agent/Workflow 运行时配置未形成一致的生效与并发版本语义 | `server-py/app/services/config/`、Agent/Workflow runtime | 已修复 | 输入校验、运行时生效、启停和乐观版本冲突已有测试；历史回滚边界见下表 |
| P1-06 | Budget/Monitor 使用进程内状态，多 worker 下限额与统计可能不一致；同步调用可能绕过拦截 | `server-py/app/services/budget_guard.py`、`server-py/app/routes/monitor.py` | 上线前外部验收 | 单实例真实 Redis 原子预留/结算、PG 业务日边界已通过；仍需多 worker 并发、跨午夜长跑、依赖故障和账单对账 |
| P1-07 | RAG CI 评测把期望文档直接作为检索结果、生成指标使用固定分数，无法发现质量退化 | `server-py/tests/evaluation/`、`server-py/scripts/run_rag_eval.py`、`.github/workflows/ci.yml` | 上线前外部验收 | 真实语料和生产检索链路评测；真实 DeepSeek 定时评测；退化样例能阻断门禁 |
| P1-08 | 依赖锁定仍未形成“服务端单一真相”：服务端直接依赖与传递依赖仍可能被 pip/uv 动态解析；CPU 容器需严格避免解析到 CUDA 版 Torch | `server-py/pyproject.toml`、`server-py/requirements.txt`、Docker/CI | 上线前外部验收 | 生成 Linux CPU `pylock.toml`（或服务端全量 `uv.lock`），Docker/CI 统一 frozen install / clean sync；Ruff lint/format 基线已建立并接入 CI required check |
| P1-09 | Alembic baseline 与 ORM 曾存在 ID 类型、索引、nullable/default/comment 漂移，历史脏数据可能阻断迁移 | `server-py/alembic/versions/002_business_integrity.py`、`003_schema_alignment.py`、`entities.py` | 上线前外部验收 | 静态 head 已对齐；真实 pgvector 小型脏数据夹具的升级、schema diff、降级再升级均通过；仍需生产数据副本测时、锁/WAL 评估和备份恢复演练 |
| P1-10 | 生产 Compose 原先只部署后端，无前端静态服务、反代和容器 readiness | `frontend/Dockerfile`、`frontend/nginx.conf`、`docker/docker-compose.prod.yml` | 上线前外部验收 | 配置静态解析和前端生产镜像构建已通过；依赖锁定完成后仍需后端镜像及 SPA/API/SSE 全链路容器 smoke |
| P1-11 | ERP/Workflow/Prompt/Monitor/Config 等关键业务缺少足够的真实数据库与失败路径测试；前端仅有少量工具测试 | `server-py/tests/`、`frontend/src/**/*.test.js` | 上线前外部验收 | 模块矩阵中的关键正常、边界、权限、并发、重复提交和依赖失败场景均有门禁 |
| P1-12 | 未知 `/api` 路由、字段 camelCase/snake_case、Prompt metrics 与保存失败 UI 等契约存在不一致 | 后端各 routes/schemas、前端各 store/view | 上线前外部验收 | 已修复本轮发现的契约并补单测；仍需由 OpenAPI/浏览器 E2E 覆盖全部 CRUD 与 SSE 事件 |

## P2：上线前治理项

| ID | 问题与影响 | 状态 | 关闭条件 |
|---|---|---|---|
| P2-01 | 后端生产镜像仍为单 worker，缺少按容量测得的 worker/资源/优雅终止参数 | 上线前外部验收 | 压测确定并发模型、资源上限、超时和优雅关闭策略 |
| P2-02 | 前端关键页面 E2E 与性能预算不足，构建仍有第三方 PURE 注释告警 | 上线前外部验收 | 浏览器 E2E、首屏与慢网性能预算达标；评估 ECharts 独立 chunk 的缓存策略 |
| P2-03 | 覆盖率、迁移 round-trip、容器 smoke 尚未形成统一 required checks | 上线前外部验收 | CI 公开阈值并阻断回归 |
| P2-04 | README 曾把直接启动描述成自动建表，并把 ERP 演练描述为正式审批 | 已修复 | 文档、页面和接口口径已统一；正式对外发布仍需业务负责人签字确认 |

## 明确产品边界

| 能力 | 当前边界 | 状态 | 若要正式上线必须增加 |
|---|---|---|---|
| ERP 审批 | 当前仅为 AI 填单和审批流程预演；输出不构成正式审批决定 | 明确产品边界 | 组织架构、真实审批人/待办、强状态机、审计、通知、撤回/转交/加签、外部 ERP 对账和业务签署 |
| Agent 通知 | `send_notify` 尚未接入，不能配置给 Agent；UI 明确显示“未接入” | 明确产品边界 | 通知渠道连接器、收件人权限、人工确认、幂等、重试、回执与审计 |
| Agent 外部工具 | 工具结果属于辅助建议，不保证第三方数据持续可用或具备执行授权 | 明确产品边界 | 工具权限分级、人工确认、幂等执行、失败补偿与第三方 SLA |
| Config/Workflow 版本 | `version` 是当前配置的乐观并发修订号，不是历史仓库；停用阻止新启动，但已受理或暂停任务可继续完成或被显式取消 | 明确产品边界 | 如需强制撤销，增加不可变 revision/audit、回滚 API、运行实例绑定版本及管理员批量终止流程 |
| RAG 回答 | 当前不能以 mock/固定分数证明事实正确性 | 明确产品边界 | 真实 golden dataset、引用核验、权限过滤、bad-case 处置和业务质量阈值 |
| Monitor 成本 | 当前看板不是财务结算或强一致计费系统 | 明确产品边界 | 供应商账单对账、不可变用量流水、时区/汇率规则和财务验收 |

## 模块覆盖与验收矩阵

| 模块 | 已有能力 | 当前状态 | 上线前必须验证 |
|---|---|---|---|
| Auth/权限 | 登录、refresh、角色依赖、会话 owner | 已修复 | 本地账号状态/角色回查、IDOR 与登出契约已回归；真实 PG 并发仍属外部门禁 |
| Chat | SSE 对话、历史、画像、角色 | 已修复 | 本地缓存隔离、取消、终态和持久化失败已回归；多 worker 属外部门禁 |
| Knowledge | 上传、切片、混合检索、来源、会话 | 已修复 | 本地事务、owner、来源和删除一致性已回归；真实 PG/pgvector 属外部门禁 |
| RAG 质量 | golden dataset 与评测框架 | 上线前外部验收 | 真实检索/生成、faithfulness/recall/factual、bad cases、性能与成本 |
| Agent | ReAct、工具、报告 | 已修复 | 配置、步数、工具白名单、失败终态和 owner 已回归；外部工具 SLA/人工确认属产品边界 |
| Workflow | 模板、运行、暂停/恢复 | 上线前外部验收 | 代码已具备 Redis snapshot、owner/锁、显式取消；重启和多 worker 尚待真实环境 |
| ERP 技术链路 | 填单、预审演练、记录 | 上线前外部验收 | 代码已具备 owner、幂等、强校验和错误回滚；真实 PG 并发尚待验证 |
| ERP 正式审批 | 未提供 | 明确产品边界 | 见“明确产品边界”，未完成前不得作为正式审批上线 |
| Prompt | 模板 CRUD、测试、A/B | 已修复 | admin 权限、统一定价、版本冲突、保存失败和 SSE abort 已本地回归 |
| Monitor/Budget | 用量展示、预算配置 | 上线前外部验收 | 真实 PG/Redis 单实例预算、上海午夜边界与时区展示已验证；多 worker 原子性、跨午夜长跑、持久化失败、账单对账仍待验收 |
| Config | Agent/Workflow/Prompt 配置 | 明确产品边界 | 当前生效/并发语义已闭环；不可变历史、回滚和强制撤销未提供 |
| Frontend | Vue SPA、路由、stores、主要页面 | 上线前外部验收 | 构建、Lint、store 测试和登录 smoke 已通过；其余关键旅程 E2E 尚缺 |
| CI/依赖 | backend/frontend jobs | 上线前外部验收 | PG/Redis 服务与构建门禁已补；依赖锁、真实 runner 结果、type/coverage required checks 尚缺 |
| 数据库迁移 | Alembic baseline、容器启动迁移 | 上线前外部验收 | 小型历史脏数据、PGVector 升降级与 schema diff 已通过；备份恢复、大数据量锁/WAL、滚动升级仍待验收 |
| 部署运维 | Compose、探针、前端反代 | 上线前外部验收 | 配置解析、前端生产镜像、Nginx `/healthz` 与 SPA `/login` 容器 smoke 已通过；后端镜像、API/SSE、readiness、滚动升级与回滚仍待实测 |

## 上线前外部验收门禁

排期、证据栏与产品边界会签模板见 [production-acceptance-schedule.md](production-acceptance-schedule.md)（T1–T4 + PB）。关闭门禁时必须回填该清单中的负责人、日期与证据链接。

以下项目必须有可追溯报告，不能以单元测试或本地 mock 替代：

1. 生产数据规模的 PostgreSQL + pgvector 与 Redis 升级测时、锁/WAL、备份恢复和多 worker 集成；小型脏数据迁移往返已完成，不能替代该项。
2. Chat、Agent、Workflow、ERP 在进程重启、客户端断线、重复提交和并发恢复下的数据一致性。
3. 真实 LLM/Embedding/Reranker 的 RAG 质量、引用忠实度、延迟、Token 成本和 bad-case 分布。
4. 容量、长时间 SSE、外部依赖超时、Redis/DB 短暂不可用、磁盘/内存压力和优雅降级。
5. 认证授权、跨用户/跨角色数据隔离、上传与工具权限的专项验证；不包含仅属于密钥占位符之类的小项。
6. 浏览器级关键旅程：登录、Chat、知识库、Agent、Workflow、ERP 预审、Prompt 管理和退出。
7. Python 3.12 / Linux CPU 的锁文件 clean sync、`uv pip check` 和镜像 smoke；仓库根目录的历史 `uv.lock` 已移除，服务端锁定证据必须来自 `server-py/` 的全量锁文件。

## 本轮验证基线

| 检查 | 当前结果 | 门禁状态 |
|---|---|---|
| 后端非 live/slow 全量 | Python 3.12 + 临时 PostgreSQL 16/pgvector + Redis 7：185 passed，15 deselected；仅 2 个第三方弃用告警 | 通过；真实 LLM/RAG、慢测、容量和多 worker 不在此结果内 |
| 后端静态检查 | Ruff `app tests alembic` 全通过；mypy 74 个源文件 0 errors；compileall 通过 | 通过 |
| Ruff formatter | `ruff format --check app tests alembic`：116 files already formatted；`server-py/pyproject.toml` 行宽 120；CI backend job 已跑 `ruff check` + `format --check` | 通过 |
| Alembic | 临时 PostgreSQL 16 + pgvector：fresh upgrade、`alembic check`、001 脏数据夹具升级到 003、003→002→003→001→003 往返均通过；文档、切片和审批异常数据均保留并规范化，HNSW 存在；`Asia/Shanghai` DB session 下 UTC-naive 默认值仍正确 | 小型真实实例通过；生产数据副本测时、备份恢复与锁/WAL 仍属外部门禁 |
| 后端 integration 子集 | 真实 PostgreSQL 上 28 passed；认证种子、登录/refresh/IDOR、知识库接口、SSE 与 Agent 持久化等均通过 | 通过；并发故障、重启、多 worker 和真实模型仍属外部门禁 |
| Monitor/Budget 在线夹具 | 上海业务日 00:00 两侧的 PG 聚合、近 7 日分组和带偏移展示通过；Redis 从 PG 基线原子预留、结算与业务日 TTL 通过 | 单实例通过；跨午夜长跑和多 worker 压测仍待验收 |
| 前端 lint / unit / build | ESLint 通过；5 个文件 18 tests passed；生产构建通过，ECharts 独立 chunk 491.57 kB；仅第三方 PURE 注释告警 | 本地通过；完整浏览器 E2E/性能仍待验收 |
| 浏览器登录 smoke | 未登录访问重定向 `/login?redirect=/chat`；全屏布局、空表单双字段校验通过；控制台 0 warning/error | 通过（仅登录入口） |
| Compose 静态解析 | 开发与生产配置均通过显式 `docker compose -f ... config --quiet` | 通过（仅静态） |
| 依赖可复现性 | 临时 Linux 解析得到 143 包且短期已有 10 个版本漂移；PyPI Torch 会额外引入 CUDA 依赖 | 上线前外部验收 |
| Docker 镜像与容器 smoke | 最终源码的前端多阶段镜像构建成功；一次性 Nginx 容器 `/healthz` 与 SPA `/login` 均 200；临时 PostgreSQL/pgvector 与 Redis 已用于迁移和集成验证 | 部分通过；后端镜像与 API/SSE 全链路 smoke 仍待依赖锁定后验收 |

## 变更状态维护规则

- 只有修复代码和相关本地回归均完成，才可标为 `已修复`；真实依赖、生产拓扑或业务签署必须另列 `上线前外部验收`。
- `上线前外部验收` 必须链接验收环境、命令、结果、负责人和日期。
- `明确产品边界` 必须同步 README、UI 文案、API 文档和对外演示口径。
- 任一 P0 未关闭，或任一外部门禁无证据，整体状态保持 **NO-GO**。
