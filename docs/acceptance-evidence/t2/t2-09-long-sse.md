# T2-09 Long SSE Soak

- Date: 2026-07-16 17:20:51
- Endpoint: `GET /health/stream` (ping every 10s)
- Target duration: 30 minutes
- Observed duration: 1810.0s
- Ping events: 181
- Max inter-ping gap: 10.005613327026367s
- Frontend /health/live after soak: True
- Nginx proxy_read_timeout: 3600s
- Uvicorn workers: 2

Pass: no silent hang; stream stayed open for ≥30 minutes with periodic ping events.
