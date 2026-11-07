FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev
# Docker COPY does not remove destination files from earlier layers; stale
# unchecked-hash .pyc files would otherwise shadow the newly copied source.
RUN find /app -name "__pycache__" -type d -prune -exec rm -rf {} +

CMD ["uv", "run", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
