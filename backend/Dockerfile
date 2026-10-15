# syntax=docker/dockerfile:1

# 只用 Docker Hub 的 python:3.12-slim 作基础镜像，uv 用 pip 装（走 PyPI）。
# 之前是 COPY --from=ghcr.io/astral-sh/uv 静态镜像，但国内各加速站
# （ghcr.m.daocloud.io 等）经常 502，构建会因为拉不到 uv 直接失败；
# uv 在 PyPI 上有官方 wheel（自带二进制），和 uv sync 用的是同一个源，更稳。
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models

# 需要固定版本时写成 pip install --no-cache-dir uv==0.12.16
RUN pip install --no-cache-dir uv

WORKDIR /app

# ---- 依赖层：只要 pyproject/uv.lock 没变就命中缓存 ----
FROM base AS deps
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# ---- 运行层 ----
FROM base AS runtime
COPY --from=deps /app/.venv /app/.venv
COPY . .

RUN mkdir -p /models && chmod -R 777 /models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
