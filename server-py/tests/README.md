# 测试环境说明

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TEST_DATABASE_URL` | 集成测试用 PostgreSQL 连接串 | `postgresql+asyncpg://test:test@localhost:5434/workmind_test` |
| `DEEPSEEK_API_KEY` | Mock 测试用占位 Key | `test-deepseek-key-for-testing` |
| `AUTH_ENABLED` | 是否启用 JWT（现有集成测试默认 `false`） | `false` |
| `JWT_SECRET` | JWT 签名密钥（≥32 字符） | 测试占位符 |

在 `tests/conftest.py` 中于 import app 之前注入，本地运行前请确保 `DATABASE_URL` 已通过 `.env` 或上述变量配置。

## 运行命令

```bash
cd server-py
uv run pytest tests/integration/ -q -m "not live and not slow"
```
