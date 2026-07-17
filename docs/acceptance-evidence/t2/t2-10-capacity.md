# T2-10 Capacity / Ops Parameters

- Date: 2026-07-16 16:50:05
- Topology: `docker/docker-compose.prod.yml`
- Workers: `UVICORN_WORKERS=2` (entrypoint default ≥2)
- Keep-alive timeout: `UVICORN_TIMEOUT=120`
- Graceful shutdown: `UVICORN_GRACEFUL_TIMEOUT=30`
- Nginx SSE proxy timeout: `3600s` (`frontend/nginx.conf`)
- Health probes: `/health/*` exempt from rate limit

## Light load (GET /health/live)

| Metric | Value |
|---|---|
| Concurrency | 20 workers × 200 requests |
| Success | 200 |
| Errors | 0 |
| p50 latency (ms) | 12.04 |
| p95 latency (ms) | 19.22 |

## docker stats (after probe)

```
workmind7-prod-app-1	0.47%	882.8MiB / 15.37GiB	5.61%
workmind7-prod-frontend-1	0.00%	18.93MiB / 15.37GiB	0.12%
workmind7-prod-redis-1	0.35%	5.551MiB / 15.37GiB	0.04%
workmind7-prod-postgres-1	0.00%	46.44MiB / 15.37GiB	0.30%
workmind7-pgvector	0.00%	46.58MiB / 15.37GiB	0.30%
workmind7-redis	0.33%	13.29MiB / 15.37GiB	0.08%
```

## Recommended production parameters

| Parameter | Value | Notes |
|---|---|---|
| UVICORN_WORKERS | 2 | Validated under T2 multi-worker lock/budget |
| UVICORN_TIMEOUT | 120 | keep-alive |
| UVICORN_GRACEFUL_TIMEOUT | 30 | aligns with workflow/ERP shutdown wait |
| nginx proxy_read_timeout | 3600s | long SSE |
| APP memory baseline | ~900MiB @ 2 workers (CPU torch stack) | scale host accordingly |

Pass criteria satisfied: worker count / timeouts / graceful shutdown written and light concurrency probe completed.
