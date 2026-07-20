FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv：Docker/CI 统一用锁定文件做 frozen install（T1-03）
COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv

# T1-05：服务端依赖唯一真相源是 requirements.linux-cpu.lock.txt
#（Linux CPU 解析，torch+cpu、无 nvidia-*；重新生成见 scripts/regenerate_linux_cpu_lock.sh）
COPY requirements.linux-cpu.lock.txt .

RUN uv pip install --system --no-cache \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --index-strategy unsafe-best-match \
    -r requirements.linux-cpu.lock.txt \
    && uv pip check --system \
    && python -c "import torch; assert '+cpu' in torch.__version__ or not torch.cuda.is_available(), torch.__version__; print('torch', torch.__version__)"

COPY . .

# Windows 检出可能带 CRLF，Linux 容器无法 exec；构建时强制 LF
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

ENV HF_HOME=/data/huggingface_cache
ENV EMBEDDING_DEVICE=cpu
ENV PORT=3001

# 非 root 运行：降低容器逃逸影响；确保挂载卷（uploads、HF 缓存）可写
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/uploads /data/huggingface_cache \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 3001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
