# syntax=docker/dockerfile:1

# uv 的官方镜像在 ghcr.io，国内服务器拉取可能极慢（实测 20MB 要 20 多分钟）。
# 可在根目录 .env 里改 UV_IMAGE 走镜像加速，例如：
#   ghcr.m.daocloud.io/astral-sh/uv:latest
#   ghcr.nju.edu.cn/astral-sh/uv:latest
ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest
FROM ${UV_IMAGE} AS uv

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models

COPY --from=uv /uv /uvx /bin/

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
