#!/usr/bin/env bash
# 在 Linux (manylinux) 上重新生成 server-py/requirements.linux-cpu.lock.txt
# 用法（仓库根或本目录）：
#   docker run --rm -v "$PWD:/work" -w /work/server-py python:3.12-slim bash scripts/regenerate_linux_cpu_lock.sh
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -q uv
uv pip compile requirements.txt -o requirements.linux-cpu.lock.txt \
  --python-platform x86_64-manylinux_2_28 \
  --python-version 3.12 \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match
if grep -qiE '^nvidia-' requirements.linux-cpu.lock.txt; then
  echo "FAIL: nvidia-* present after compile" >&2
  exit 1
fi
if ! grep -qiE '^torch==.*\+cpu' requirements.linux-cpu.lock.txt; then
  echo "FAIL: torch+cpu missing after compile" >&2
  exit 1
fi
echo "OK: wrote requirements.linux-cpu.lock.txt"
grep -iE '^torch==' requirements.linux-cpu.lock.txt
