#!/bin/sh
set -e

PORT="${PORT:-3001}"
MAX_RETRIES="${MIGRATION_MAX_RETRIES:-30}"

echo "[entrypoint] Running alembic upgrade head..."

retry=0
until alembic upgrade head; do
  retry=$((retry + 1))
  if [ "$retry" -ge "$MAX_RETRIES" ]; then
    echo "[entrypoint] Migration failed after ${MAX_RETRIES} attempts"
    exit 1
  fi
  echo "[entrypoint] DB not ready, retry ${retry}/${MAX_RETRIES} in 2s..."
  sleep 2
done

# T2：多 worker 拓扑由 UVICORN_WORKERS 控制（验收默认 ≥2；单实例调试可设 1）
WORKERS="${UVICORN_WORKERS:-2}"
TIMEOUT="${UVICORN_TIMEOUT:-120}"
GRACEFUL="${UVICORN_GRACEFUL_TIMEOUT:-30}"

echo "[entrypoint] Migrations complete. Starting uvicorn on port ${PORT} (workers=${WORKERS})..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${WORKERS}" \
  --timeout-keep-alive "${TIMEOUT}" \
  --timeout-graceful-shutdown "${GRACEFUL}"
