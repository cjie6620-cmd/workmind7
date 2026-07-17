# T2-14 Disk / Memory Observation

- Date: 2026-07-16 16:50:33
- Mode: **observation sample** under multi-worker prod compose (not artificial disk-full injection)

## docker stats

```
workmind7-prod-app-1	0.45%	883.6MiB / 15.37GiB	5.61%
workmind7-prod-frontend-1	0.00%	18.19MiB / 15.37GiB	0.12%
workmind7-prod-redis-1	0.35%	5.836MiB / 15.37GiB	0.04%
workmind7-prod-postgres-1	0.01%	47.29MiB / 15.37GiB	0.30%
workmind7-pgvector	0.00%	45.93MiB / 15.37GiB	0.29%
workmind7-redis	0.33%	12.87MiB / 15.37GiB	0.08%
```

## filesystem

```
Filesystem      Size  Used Avail Use% Mounted on
overlay        1007G   36G  920G   4% /
overlay        1007G   36G  920G   4% /
```

## memory

```
MemTotal:       16115860 kB
MemFree:          668696 kB
MemAvailable:   13666612 kB
Buffers:          311436 kB
Cached:         11599336 kB
```

## Degradation / alerts expected in production

- App readiness fails closed when Postgres/Redis unavailable (validated T2-05/06)
- Embedding preload failures are explicit WARN / optional `EMBEDDING_REQUIRED`
- Recommend host alerts: disk >85%, container RSS > host budget, Postgres volume fill

Pass as observation evidence with residual risk: no synthetic disk-full fault injected this pass.

## 观测降级签批（T2-14）

| 字段 | 内容 |
|---|---|
| 结论 | 降级为**观测项**（本轮不注入磁盘打满/OOM） |
| 残留风险 | 生产需配置磁盘>85%、容器 RSS、PG volume 告警；依赖故障已由 T2-05/06 覆盖 fail-closed |
| 复测触发 | 上线后首次容量告警演练或压测周 |
| 验收执行签字 | 验收执行 / 2026-07-16 / **同意观测降级** |
| 运维/SRE 会签 | （可后续补签；不阻塞轨 2 退出，但无条件 GO 前建议补齐） |
