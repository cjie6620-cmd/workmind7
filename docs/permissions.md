# WorkMind AI — 路由权限矩阵

> 与 `PRODUCTION-READINESS.md` W0b-2 保持同步。最后更新：2026-07-13

## 原则

- `userId` / `sessionId` **不得**由客户端随意指定归属
- 用户 ID 从 JWT `sub` 注入（`Depends(get_current_user)`）
- 会话访问前校验 `assert_session_owner`

## 权限矩阵

| 路由前缀 | 最低角色 | 说明 |
|----------|---------|------|
| `/api/chat/*` | `user` | 仅访问本人 session / profile |
| `/api/knowledge/*` | `user` | 上传/删除需 `user`；查询可读 |
| `/api/agent/*` | `user` | 同上 |
| `/api/workflow/*` | `user` | 同上 |
| `/api/erp/*` | `user` | 同上 |
| `/api/prompt/*` | `admin` | Prompt 调试台 |
| `/api/configs/*` | `admin` | 系统配置 |
| `/api/monitor/*` | `admin` | 监控与预算 |
| `/api/auth/login` | 无 | 公开 |
| `/api/auth/refresh` | 无 | 需有效 refresh token |
| `/health/live` | 无 | 存活探针 |
| `/health/ready` | 无 | 就绪探针（DB + Redis） |

## IDOR 防护

| 端点 | 防护措施 |
|------|---------|
| `GET /api/chat/sessions` | 按 `user_id` 过滤 |
| `GET /api/chat/history/{id}` | `assert_session_owner` |
| `POST /api/chat/stream` | `assert_session_owner` + `user_id` 持久化 |
| `DELETE /api/chat/sessions/{id}` | `assert_session_owner` + 按 `user_id` 删除 |
| `GET /api/agent/history/{id}` | `assert_session_owner` |
| `GET /api/chat/profile` | 使用当前用户 ID |
| `GET /api/agent/sessions` | 按 `user_id` 过滤 |
| `GET /api/knowledge/history/{id}` | `assert_session_owner` |
| `GET /api/knowledge/sessions` | 按 `user_id` 过滤 |
| `POST /api/knowledge/query/stream` | `assert_session_owner` + `user_id` 持久化 |
| `GET /api/agent/reports` | 按 `user_id` 隔离（Redis key） |
| `GET /api/agent/reports/{id}` | 仅本人报告 |

## 回滚

认证问题：`AUTH_ENABLED=false` 绕过中间件（仅开发/紧急回滚）。
