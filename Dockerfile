# Production image for the football agent (FastAPI + APScheduler + LightGBM).
# Build on the target host (`docker compose build`) so the image matches its architecture.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    ML_ARTIFACT_DIR=artifacts/ml

# LightGBM needs the OpenMP runtime (libgomp on Debian).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cached layer); --no-dev skips pytest/ruff.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Non-root runtime user; /app/artifacts exists so a fresh named volume inherits appuser ownership.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/artifacts \
    && chown -R appuser:appuser /app

# Git SHA baked at build time (`.git` is not in the image); defaults to "unknown".
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

USER appuser

EXPOSE 8000

# `--factory`: app/api/main.py exposes create_app(), not a module-level `app`.
CMD ["uvicorn", "app.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
