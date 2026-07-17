# RAG 评测门禁

> 与 [生产就绪清单](production-readiness.md) 保持同步。最后更新：2026-07-16

## Golden Dataset

- 路径：`server-py/tests/fixtures/golden_dataset.json`
- 规模：80 条（覆盖 single_hop / multi_hop / edge_case）
- 版本：纳入 Git，变更需在 PR 说明中注明

## 声明阈值（`tests/evaluation/conftest.py`）

以下阈值已写入测试配置，但当前 non-live 套件使用模拟检索/固定生成分数，尚不能作为真实业务质量的阻断证据。只有生产检索链路和真实评测数据接入后，才可将其升级为上线门禁。

| 指标 | 阻断 (block) | 告警 (warn) |
|------|-------------|-------------|
| Faithfulness | ≥ 0.70 | ≥ 0.85 |
| Context Recall | ≥ 0.60 | ≥ 0.80 |
| Factual Correctness | ≥ 0.60 | ≥ 0.75 |
| Precision@4 | ≥ 0.20 | ≥ 0.50 |
| Recall@4 | ≥ 0.60 | ≥ 0.75 |

## 运行方式

```bash
cd server-py

# CI / 本地 mock 评测（不调真实 LLM；仅验证流程，不代表业务质量）
python -m pytest -m "evaluation and not live and not slow" -q

# Live 评测（需真实 DEEPSEEK_API_KEY 和已就绪的测试语料/依赖）
python -m pytest -m "evaluation and live" -q
```

## GitHub Actions

- **backend** job（PR / push）：运行 `pytest -m "not live and not slow"`，其中 mock 评测只验证代码路径和阈值机制
- **evaluation** job：`workflow_dispatch` + 每周一 02:00 UTC cron 当前仍运行 non-live 套件
- 当前 workflow **没有**执行真实 live 质量评测；真实检索、生成质量和阈值退化检测仍是上线前外部验收门禁

## 模型要求

- 评测 LLM 必须使用国产模型：**deepseek-chat**
- 禁止在评测中使用 OpenAI / Anthropic 等国外 API
