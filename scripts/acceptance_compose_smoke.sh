#!/usr/bin/env bash
# T1-04 / T1-06 smoke against docker compose prod stack.
# From repo root:
#   bash scripts/acceptance_compose_smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose --env-file "$ROOT/server-py/.env" -f "$ROOT/docker/docker-compose.prod.yml")
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
APP_PORT="${APP_PORT:-3001}"

echo "== compose up --build =="
"${COMPOSE[@]}" up -d --build

echo "== wait ready =="
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${APP_PORT}/health/ready" >/dev/null; then
    echo "app ready after ${i} attempts"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "FAIL: /health/ready timeout" >&2
    "${COMPOSE[@]}" logs --tail=80 app
    exit 1
  fi
  sleep 5
done

echo "== T1-04: app health + API =="
curl -sf "http://127.0.0.1:${APP_PORT}/health/ready" | tee /tmp/wm-ready.json
curl -sf -o /dev/null -w "live=%{http_code}\n" "http://127.0.0.1:${APP_PORT}/health/live"

echo "== T1-06: frontend proxy healthz + login + /health/ready =="
curl -sf "http://127.0.0.1:${FRONTEND_PORT}/healthz"
curl -sf -o /dev/null -w "login=%{http_code}\n" "http://127.0.0.1:${FRONTEND_PORT}/login"
curl -sf "http://127.0.0.1:${FRONTEND_PORT}/health/ready" | tee /tmp/wm-fe-ready.json

echo "== short SSE/API probe (auth login if enabled) =="
# Prefer frontend proxy path for full-chain smoke
LOGIN_CODE=$(curl -s -o /tmp/wm-login.json -w "%{http_code}" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  "http://127.0.0.1:${FRONTEND_PORT}/api/auth/login" || true)
echo "login_http=${LOGIN_CODE}"
if [ "$LOGIN_CODE" = "200" ]; then
  TOKEN=$(python -c "import json; print(json.load(open('/tmp/wm-login.json')).get('accessToken') or json.load(open('/tmp/wm-login.json')).get('access_token') or '')")
  if [ -n "$TOKEN" ]; then
    curl -sf -o /tmp/wm-sessions.json -H "Authorization: Bearer ${TOKEN}" \
      "http://127.0.0.1:${FRONTEND_PORT}/api/chat/sessions" || true
    echo "sessions_probe=ok"
  fi
fi

echo "SMOKE_OK"
