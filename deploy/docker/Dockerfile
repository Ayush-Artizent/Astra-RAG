# One Dockerfile for every deployable unit. Build with:
#   docker build -f deploy/docker/Dockerfile --build-arg SERVICE=rag-api -t astra/rag-api .
# SERVICE is a uv workspace member: rag-api | rag-ingest | rag-mcp | rag-eval
ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.12-python${PYTHON_VERSION}-bookworm-slim AS build
ARG SERVICE
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
# Dependency layer (cached until the lockfile changes)
COPY pyproject.toml uv.lock ./
COPY packages/rag-core/pyproject.toml packages/rag-core/
COPY packages/rag-parsers/pyproject.toml packages/rag-parsers/
COPY services/rag-ingest/pyproject.toml services/rag-ingest/
COPY services/rag-api/pyproject.toml services/rag-api/
COPY services/rag-mcp/pyproject.toml services/rag-mcp/
COPY services/rag-eval/pyproject.toml services/rag-eval/
COPY sdk/python/pyproject.toml sdk/python/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package ${SERVICE}
# Source layer
COPY packages packages
COPY services services
COPY sdk/python sdk/python
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package ${SERVICE}

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 astra && useradd --system --uid 10001 --gid astra astra
COPY --from=build --chown=astra:astra /src/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 ASTRA_LOG_JSON=true
WORKDIR /app
USER 10001
# Each k8s manifest sets its own command (uvicorn app, worker, cronjob).
CMD ["python", "-c", "print('set a command for this service')"]
